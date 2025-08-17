import re
from decimal import Decimal
from typing import List
import graphene
from graphene_django import DjangoObjectType
from graphene_django.filter import DjangoFilterConnectionField
from graphql import GraphQLError
from django.db import transaction
from django.utils import timezone

from crm.filters import CustomerFilter, ProductFilter, OrderFilter

from .models import Customer, Product, Order

# -----------------------
# GraphQL Types
# -----------------------
class CustomerType(DjangoObjectType):
    class Meta:
        model = Customer
        filterset_class = CustomerFilter
        fields = ("id", "name", "email", "phone", "address")
        interfaces = (graphene.relay.Node,)


class ProductType(DjangoObjectType):
    class Meta:
        model = Product
        filterset_class = ProductFilter
        fields = ("id", "name", "price", "stock")
        interfaces = (graphene.relay.Node,)


class OrderType(DjangoObjectType):
    class Meta:
        model = Order
        filterset_class = OrderFilter
        fields = ("id", "customer", "products", "order_date", "total_amount")
        interfaces = (graphene.relay.Node,)


# For bulk error reporting
class BulkErrorType(graphene.ObjectType):
    index = graphene.Int()          # position in the input list
    email = graphene.String()
    message = graphene.String()


# For bulk input
class CustomerInput(graphene.InputObjectType):
    name = graphene.String(required=True)
    email = graphene.String(required=True)
    phone = graphene.String()  # optional

# -----------------------
# Validators
# -----------------------
EMAIL_EXISTS_MSG = "Email already exists."
PHONE_RE = re.compile(r"^(\+\d{10,15}|\d{3}-\d{3}-\d{4})$")  # e.g., +12345678901 or 123-456-7890


def validate_email_unique(email: str):
    if Customer.objects.filter(email__iexact=email).exists():
        raise GraphQLError(EMAIL_EXISTS_MSG)


def validate_phone(phone: str | None):
    if phone and not PHONE_RE.match(phone):
        raise GraphQLError("Invalid phone format. Use +1234567890 or 123-456-7890.")


def validate_price_and_stock(price: Decimal | float, stock: int | None):
    try:
        price = Decimal(str(price))
    except Exception:
        raise GraphQLError("Price must be a valid decimal number.")
    if price <= 0:
        raise GraphQLError("Price must be positive.")
    if stock is not None and int(stock) < 0:
        raise GraphQLError("Stock cannot be negative.")
    return price, int(stock) if stock is not None else 0

# -----------------------
# Mutations
# -----------------------
class CreateCustomer(graphene.Mutation):
    class Arguments:
        name = graphene.String(required=True)
        email = graphene.String(required=True)
        phone = graphene.String()

    ok = graphene.Boolean()
    message = graphene.String()
    customer = graphene.Field(CustomerType)

    @staticmethod
    def mutate(root, info, name: str, email: str, phone: str | None = None):
        validate_email_unique(email)
        validate_phone(phone)

        customer = Customer(name=name.strip(), email=email.strip(), phone=phone or "")
        customer.save()

        return CreateCustomer(ok=True, message="Customer created.", customer=customer)
    

class BulkCreateCustomers(graphene.Mutation):
    class Arguments:
        customers = graphene.List(CustomerInput, required=True)

    created = graphene.List(CustomerType)
    errors = graphene.List(BulkErrorType)

    @staticmethod
    def mutate(root, info, customers: List[CustomerInput]):
        created_objs: list[Customer] = []
        errors: list[BulkErrorType] = []

        # Use a transaction with per-item savepoints to allow partial success
        with transaction.atomic():
            for idx, c in enumerate(customers or []):
                spid = transaction.savepoint()
                try:
                    if not c.name or not c.email:
                        raise GraphQLError("Both name and email are required.")
                    validate_email_unique(c.email)
                    validate_phone(c.phone)
                    obj = Customer(name=c.name.strip(), email=c.email.strip(), phone=(c.phone or ""))
                    obj.save()
                    created_objs.append(obj)
                    transaction.savepoint_commit(spid)
                except GraphQLError as e:
                    transaction.savepoint_rollback(spid)
                    errors.append(BulkErrorType(index=idx, email=getattr(c, "email", None), message=str(e)))
                except Exception as e:
                    transaction.savepoint_rollback(spid)
                    errors.append(BulkErrorType(index=idx, email=getattr(c, "email", None), message="Unexpected error: " + str(e)))

        return BulkCreateCustomers(created=created_objs, errors=errors)
    
class CreateProduct(graphene.Mutation):
    class Arguments:
        name = graphene.String(required=True)
        # Using Float for broad compatibility; convert safely to Decimal
        price = graphene.Float(required=True)
        stock = graphene.Int()  # default 0

    ok = graphene.Boolean()
    product = graphene.Field(ProductType)
    message = graphene.String()

    @staticmethod
    def mutate(root, info, name: str, price: float, stock: int | None = None):
        cleaned_price, cleaned_stock = validate_price_and_stock(price, stock)
        if not name.strip():
            raise GraphQLError("Product name is required.")

        product = Product(name=name.strip(), price=cleaned_price, stock=cleaned_stock)
        product.save()
        return CreateProduct(ok=True, product=product, message="Product created.")


class CreateOrder(graphene.Mutation):
    class Arguments:
        customer_id = graphene.ID(required=True)
        product_ids = graphene.List(graphene.ID, required=True)
        order_date = graphene.DateTime()  # optional

    ok = graphene.Boolean()
    order = graphene.Field(OrderType)
    message = graphene.String()

    @staticmethod
    def mutate(root, info, customer_id, product_ids, order_date=None):
        # Validate presence
        if not product_ids:
            raise GraphQLError("At least one product must be selected.")

        # Fetch and validate customer
        try:
            customer_pk = int(customer_id)
        except (TypeError, ValueError):
            raise GraphQLError("Invalid customer ID.")
        customer = Customer.objects.filter(pk=customer_pk).first()
        if not customer:
            raise GraphQLError("Customer not found.")

        # Fetch products
        try:
            product_pks = [int(pid) for pid in product_ids]
        except (TypeError, ValueError):
            raise GraphQLError("All product IDs must be integers.")
        products = list(Product.objects.filter(pk__in=product_pks))
        missing = set(product_pks) - {p.pk for p in products}
        if missing:
            raise GraphQLError(f"Invalid product ID(s): {sorted(missing)}")

        # Calculate total using Decimal to avoid float drift
        total_amount = sum((p.price for p in products), Decimal("0.00"))

        # Create order in a transaction
        with transaction.atomic():
            order = Order.objects.create(
                customer=customer,
                order_date=order_date or timezone.now(),
                total_amount=total_amount,
            )
            order.products.set(products)

        return CreateOrder(ok=True, order=order, message="Order created.")
    
# -----------------------
# Root Query & Mutation
# -----------------------
class Mutation(graphene.ObjectType):
    create_customer = CreateCustomer.Field()
    bulk_create_customers = BulkCreateCustomers.Field()
    create_product = CreateProduct.Field()
    create_order = CreateOrder.Field()

# ----------------- Query with Filters -----------------
class Query(graphene.ObjectType):
    hello = graphene.String(default_value="Hello, GraphQL!")
    all_customers = DjangoFilterConnectionField(CustomerType, order_by=graphene.List(of_type=graphene.String))
    all_products = DjangoFilterConnectionField(ProductType, order_by=graphene.List(of_type=graphene.String))
    all_orders = DjangoFilterConnectionField(OrderType, order_by=graphene.List(of_type=graphene.String))

    def resolve_all_customers(self, info, order_by=None, **kwargs):
        qs = Customer.objects.all()
        if order_by:
            qs = qs.order_by(*order_by)
        return qs

    def resolve_all_products(self, info, order_by=None, **kwargs):
        qs = Product.objects.all()
        if order_by:
            qs = qs.order_by(*order_by)
        return qs

    def resolve_all_orders(self, info, order_by=None, **kwargs):
        qs = Order.objects.all()
        if order_by:
            qs = qs.order_by(*order_by)
        return qs


schema = graphene.Schema(query=Query, mutation=Mutation)

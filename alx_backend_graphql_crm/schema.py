import graphene
from crm.schema import Query as CRMQuery, Mutation as CRMMutation

# Root Query class (extendable if you add more apps later)
class Query(CRMQuery, graphene.ObjectType):
    pass

# Root Mutation class (extendable as well)
class Mutation(CRMMutation, graphene.ObjectType):
    pass

# Final Schema combining Queries + Mutations
schema = graphene.Schema(query=Query, mutation=Mutation)
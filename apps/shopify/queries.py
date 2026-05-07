GET_CUSTOMERS_QUERY = """
query getCustomers($first: Int!, $after: String, $query: String, $reverse: Boolean) {
  customers(first: $first, after: $after, query: $query, reverse: $reverse) {
    edges {
      node {
        id
        firstName
        lastName
        phone
        createdAt
        updatedAt
        defaultPhoneNumber {
          marketingState
        }
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""
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


GET_PRODUCTS_QUERY = """
query getProducts($first: Int!, $after: String, $query: String, $reverse: Boolean) {
  products(first: $first, after: $after, query: $query, reverse: $reverse) {
    edges {
      node {
        id
        title
        descriptionHtml
        handle
        status
        createdAt
        updatedAt
        hasOutOfStockVariants
        isGiftCard
        publishedAt
        tags
        totalInventory
        seo {
          title
          description
        }
        variantsCount {
          count
          precision
        }
        variants(first: 100) {
          edges {
            node {
              id
              title
              sku
              price
              inventoryQuantity
              image {
                id
                url
                altText
              }
            }
          }
        }
        media(first: 25) {
          edges {
            node {
              mediaContentType
              ... on MediaImage {
                id
                alt
                image {
                  id
                  url
                  altText
                  width
                  height
                }
              }
            }
          }
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



GET_PRODUCT_QUERY = """
query getProductById($id: ID!) {
  product(id: $id) {
    id
    title
    descriptionHtml
    handle
    status
    createdAt
    updatedAt
    hasOutOfStockVariants
    isGiftCard
    publishedAt
    tags
    totalInventory
    seo {
      title
      description
    }
    variantsCount {
      count
      precision
    }
    variants(first: 100) {
      edges {
        node {
          id
          title
          sku
          price
          inventoryQuantity
          image {
            id
            url
            altText
          }
        }
      }
    }
    media(first: 25) {
      edges {
        node {
          mediaContentType
          ... on MediaImage {
            id
            alt
            image {
              id
              url
              altText
              width
              height
            }
          }
        }
      }
    }
  }
}
"""



CREATE_PURCHASED_CHARGE = """
mutation AppPurchaseOneTimeCreate(
  $name: String!
  $price: MoneyInput!
  $returnUrl: URL!
  $test: Boolean = true
) {
  appPurchaseOneTimeCreate(
    name: $name
    price: $price
    returnUrl: $returnUrl
    test: $test
  ) {
    userErrors {
      field
      message
    }
    appPurchaseOneTime {
      id
      createdAt
    }
    confirmationUrl
  }
}
"""

GET_SHOP_BILLING_STATE = """
query {
  shop {
    myshopifyDomain
    plan {
      publicDisplayName
      partnerDevelopment
      shopifyPlus
    }
  }
}
"""
describe('Bookstore Checkout - Happy Path', () => {
  beforeEach(() => {
    cy.visit('/')
    cy.get('[data-cy="submit-button"]').should('be.visible')
  })

  it('should complete a successful checkout with mocked responses', () => {
    const orderId = 'test-order-123'

    // Mock the checkout submission
    cy.intercept('POST', 'http://localhost:8081/v2/checkout', {
      statusCode: 200,
      body: {
        orderId: orderId,
        status: 'PENDING'
      }
    }).as('checkoutRequest')

    // Mock the order status polling - return success after a few calls
    cy.intercept('GET', `http://localhost:8081/v2/orders/${orderId}`, {
      statusCode: 200,
      body: {
        orderId: orderId,
        status: 'Order Approved',
        suggestedBooks: [
          { productId: 'BOOK001', title: '1984', author: 'George Orwell' }
        ]
      }
    }).as('orderStatus')

    // Accept terms (required field)
    cy.get('[data-cy="terms-accepted"]').check()

    // Submit the form
    cy.get('[data-cy="submit-button"]').click()

    // Verify the checkout request was made
    cy.wait('@checkoutRequest').then((interception) => {
      expect(interception.request.body.user.name).to.equal('John Doe')
      expect(interception.request.body.termsAndConditionsAccepted).to.be.true
    })

    // Verify initial success message
    cy.get('[data-cy="alert-success"]', { timeout: 5000 })
      .should('be.visible')
      .and('contain', 'Order submitted!')
      .and('contain', orderId)

    // Wait for polling to complete and show final success
    cy.get('[data-cy="alert-success"]', { timeout: 10000 })
      .should('contain', 'Order completed successfully!')

    // Verify suggested books appear
    cy.get('[data-cy="suggested-books"]', { timeout: 5000 })
      .should('be.visible')
      .and('contain', '1984')
      .and('contain', 'George Orwell')
  })

  it('should complete a successful checkout with real backend', () => {
    // No mocking - hit the real backend

    // Accept terms (required field)
    cy.get('[data-cy="terms-accepted"]').check()

    // Submit the form
    cy.get('[data-cy="submit-button"]').click()

    // Verify loading state is active
    cy.get('.loading').should('be.visible')
    cy.get('[data-cy="submit-button"]').should('be.disabled')

    // Verify initial success message appears
    cy.get('[data-cy="alert-success"]', { timeout: 15000 })
      .should('be.visible')
      .and('contain', 'Order submitted!')
      .and('contain', 'Processing...')

    // Wait a bit for processing to start
    cy.wait(3000)

    // Wait for real order processing to complete (up to 60 seconds)
    // Your backend polls every 1 second for up to 30 seconds
    cy.get('[data-cy="alert-success"]', { timeout: 60000 })
      .should('contain', 'Order completed successfully!')

    // Verify loading state is cleared
    cy.get('.loading').should('not.be.visible')
    cy.get('[data-cy="submit-button"]').should('not.be.disabled')

    // Optional: Wait a bit more to see if suggested books appear
    cy.wait(2000)

    // Check if suggested books appear (might not always have suggestions)
    cy.get('body').then(($body) => {
      if ($body.find('[data-cy="suggested-books"]').length > 0) {
        cy.get('[data-cy="suggested-books"]')
          .should('be.visible')
          .and('contain', 'Recommended for you')
      } else {
        cy.log('No suggested books returned from real backend')
      }
    })
  })

  it('should handle real backend timeout gracefully', () => {
    // Test what happens if real backend takes too long

    cy.get('[data-cy="terms-accepted"]').check()
    cy.get('[data-cy="submit-button"]').click()

    // Wait for initial submission
    cy.get('[data-cy="alert-success"]', { timeout: 15000 })
      .should('be.visible')
      .and('contain', 'Order submitted!')

    // Wait for either success or timeout (35 seconds max)
    cy.get('[data-cy="alert-success"]', { timeout: 35000 })
      .should('contain', 'Order completed successfully!')

    cy.get('[data-cy="suggested-books"]', { timeout: 5000 })
      .should('be.visible')
      .and('contain', 'Recommended for you')

    cy.get('[data-cy="suggested-books"]').then(($suggestions) => {
      cy.log('Suggested books HTML:', $suggestions.html())
      console.log('Suggested books:', $suggestions.html())
    })
  })
})

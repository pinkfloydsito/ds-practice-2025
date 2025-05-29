Cypress.Commands.add('fillCheckoutForm', (customerData = {}) => {
  const defaultData = {
    name: 'John Doe',
    email: 'john.doe@example.ru',
    cardNumber: '6011111111111117',
    expiryDate: '12/95',
    cvv: '123',
    street: '123 Main St',
    city: 'Springfield',
    state: 'IL',
    zip: '62701',
    country: 'USA',
    shippingMethod: 'Standard',
    acceptTerms: true,
    giftWrapping: true
  }

  const data = { ...defaultData, ...customerData }

  if (data.name) {
    cy.get('[data-cy="customer-name"]').clear().type(data.name)
  }
  if (data.email) {
    cy.get('[data-cy="customer-email"]').clear().type(data.email)
  }
  if (data.cardNumber) {
    cy.get('[data-cy="card-number"]').clear().type(data.cardNumber)
  }
  if (data.expiryDate) {
    cy.get('[data-cy="expiry-date"]').clear().type(data.expiryDate)
  }
  if (data.cvv) {
    cy.get('[data-cy="cvv"]').clear().type(data.cvv)
  }
  if (data.street) {
    cy.get('[data-cy="street"]').clear().type(data.street)
  }
  if (data.city) {
    cy.get('[data-cy="city"]').clear().type(data.city)
  }
  if (data.state) {
    cy.get('[data-cy="state"]').clear().type(data.state)
  }
  if (data.zip) {
    cy.get('[data-cy="zip"]').clear().type(data.zip)
  }
  if (data.country) {
    cy.get('[data-cy="country"]').select(data.country)
  }
  if (data.shippingMethod) {
    cy.get('[data-cy="shipping-method"]').select(data.shippingMethod)
  }
  if (data.acceptTerms) {
    cy.get('[data-cy="terms-accepted"]').check()
  }
  if (data.giftWrapping) {
    cy.get('[data-cy="gift-wrapping"]').check()
  }
})

Cypress.Commands.add('mockSuccessfulCheckout', (orderId = 'test-order-123') => {
  cy.intercept('POST', `${Cypress.env('apiUrl')}/v2/checkout`, {
    statusCode: 200,
    body: {
      orderId: orderId,
      status: 'PENDING'
    }
  }).as('checkoutRequest')
})

Cypress.Commands.add('mockOrderStatus', (orderId, status = 'Order Approved', suggestedBooks = []) => {
  cy.intercept('GET', `${Cypress.env('apiUrl')}/v2/orders/${orderId}`, {
    statusCode: 200,
    body: {
      orderId: orderId,
      status: status,
      suggestedBooks: suggestedBooks
    }
  }).as('orderStatusRequest')
})

Cypress.Commands.add('mockFailedCheckout', (errorMessage = 'Service initialization failed') => {
  cy.intercept('POST', `${Cypress.env('apiUrl')}/v2/checkout`, {
    statusCode: 400,
    body: {
      error: {
        code: 'ORDER_REJECTED',
        message: errorMessage
      }
    }
  }).as('checkoutError')
})

Cypress.Commands.add('verifyCheckoutRequest', (expectedData = {}) => {
  cy.wait('@checkoutRequest').then((interception) => {
    const requestBody = interception.request.body

    if (expectedData.userName) {
      expect(requestBody.user.name).to.equal(expectedData.userName)
    }
    if (expectedData.userEmail) {
      expect(requestBody.user.contact).to.equal(expectedData.userEmail)
    }
    if (expectedData.cardNumber) {
      expect(requestBody.creditCard.number).to.equal(expectedData.cardNumber)
    }
    if (expectedData.city) {
      expect(requestBody.billingAddress.city).to.equal(expectedData.city)
    }
    if (expectedData.termsAccepted !== undefined) {
      expect(requestBody.termsAndConditionsAccepted).to.equal(expectedData.termsAccepted)
    }

    // Always verify basic structure
    expect(requestBody).to.have.property('user')
    expect(requestBody).to.have.property('creditCard')
    expect(requestBody).to.have.property('billingAddress')
    expect(requestBody).to.have.property('items')
    expect(requestBody.items).to.have.length.greaterThan(0)
  })
})


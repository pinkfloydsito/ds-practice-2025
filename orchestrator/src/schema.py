from marshmallow import Schema, fields, validate


class DeviceSchema(Schema):
    type = fields.Str(required=True)
    model = fields.Str(required=True)
    os = fields.Str(required=True)


class BrowserSchema(Schema):
    name = fields.Str(required=True)
    version = fields.Str(required=True)


class BillingAddressSchema(Schema):
    street = fields.Str(required=True)
    city = fields.Str(required=True)
    state = fields.Str(required=True)
    zip = fields.Str(required=True)
    country = fields.Str(required=True)


class UserSchema(Schema):
    name = fields.Str(required=True)
    contact = fields.Str(required=True)


class CreditCardSchema(Schema):
    number = fields.Str(required=True, validate=validate.Length(min=15, max=16))
    expirationDate = fields.Str(required=True)
    cvv = fields.Str(required=True, validate=validate.Length(equal=3))


class ItemSchema(Schema):
    name = fields.Str(required=True)
    quantity = fields.Int(required=True, validate=validate.Range(min=1))


class CheckoutRequestSchema(Schema):
    user = fields.Nested(UserSchema, required=True)
    creditCard = fields.Nested(CreditCardSchema, required=True)
    userComment = fields.Str()
    items = fields.List(
        fields.Nested(ItemSchema), required=True, validate=validate.Length(min=1)
    )
    discountCode = fields.Str()
    shippingMethod = fields.Str(required=True)
    giftMessage = fields.Str()
    billingAddress = fields.Nested(BillingAddressSchema, required=True)
    giftWrapping = fields.Bool()
    termsAndConditionsAccepted = fields.Bool(required=True)
    notificationPreferences = fields.List(fields.Str())
    device = fields.Nested(DeviceSchema)
    browser = fields.Nested(BrowserSchema)
    appVersion = fields.Str()
    screenResolution = fields.Str()
    referrer = fields.Str()
    deviceLanguage = fields.Str()


class SuggestedBookSchema(Schema):
    bookId = fields.Str(required=True)
    title = fields.Str(required=True)
    author = fields.Str(required=True)


class OrderStatusResponseSchema(Schema):
    orderId = fields.Str(required=True)
    status = fields.Str(required=True)
    suggestedBooks = fields.List(fields.Nested(SuggestedBookSchema))


class ErrorResponseSchema(Schema):
    error = fields.Dict(keys=fields.Str(), values=fields.Str())

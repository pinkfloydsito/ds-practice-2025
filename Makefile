# Define default book values
BOOK1 ?= "Book A"
QTY1 ?= 1
BOOK2 ?= "Book B"
QTY2 ?= 2

checkout:
	@echo "Making checkout request with books: $(BOOK1) ($(QTY1)), $(BOOK2) ($(QTY2))"
	curl 'http://localhost:8081/v2/checkout' \
	  -H 'Accept: */*' \
	  -H 'Accept-Language: en-US,en;q=0.9' \
	  -H 'Content-Type: application/json' \
	  -H 'Origin: http://localhost:8080' \
	  --data-raw '{"user":{"name":"John Doe","contact":"john.doe@example.ru"},"creditCard":{"number":"6011111111111117","expirationDate":"12/95","cvv":"123"},"userComment":"Please handle with care.","items":[{"name":$(BOOK1),"quantity":$(QTY1)},{"name":$(BOOK2),"quantity":$(QTY2)}],"billingAddress":{"street":"123 Main St","city":"Springfield","state":"IL","zip":"62701","country":"USA"},"shippingMethod":"Standard","giftWrapping":true,"termsAndConditionsAccepted":true}'

get-order:
	@if [ -z "$(ORDER_ID)" ]; then \
		echo "Error: ORDER_ID is required. Usage: make get-order ORDER_ID=your-order-id"; \
		exit 1; \
	fi
	curl -X GET -vvvvv http://localhost:8081/v2/orders/$(ORDER_ID) | jq .

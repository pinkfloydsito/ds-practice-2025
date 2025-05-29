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

test-load-scenario1:
	@echo "Running Scenario 1: Non-conflicting Orders"
	@echo "5 users, spawn rate 1/sec, 30 seconds duration"
	locust -f locust/scenario1_non_conflicting.py \
		--host=http://localhost:8081 \
		--users 5 \
		--spawn-rate 1 \
		--run-time 30s \
		--headless \
		--html locust/reports/scenario1_report.html

# Scenario 2: Mixed orders (8 users, 45 seconds)
test-load-scenario2:
	@echo "Running Scenario 2: Mixed Fraudulent/Legitimate Orders"
	@echo "8 users, spawn rate 1/sec, 45 seconds duration"
	locust -f locust/scenario2_mixed_orders.py \
		--host=http://localhost:8081 \
		--users 8 \
		--spawn-rate 1 \
		--run-time 45s \
		--headless \
		--html locust/reports/scenario2_report.html

# Scenario 3: Conflicting orders (10 users, 60 seconds)
test-load-scenario3:
	@echo "Running Scenario 3: Conflicting Orders"
	@echo "10 users, spawn rate 2/sec, 60 seconds duration"
	locust -f locust/scenario3_conflicting.py \
		--host=http://localhost:8081 \
		--users 10 \
		--spawn-rate 2 \
		--run-time 60s \
		--headless \
		--html locust/reports/scenario3_report.html

# Run all scenarios sequentially
test-load-all: test-load-scenario1 test-load-scenario2 test-load-scenario3
	@echo "All load test scenarios completed!"
	@echo "Reports available in locust/reports/"

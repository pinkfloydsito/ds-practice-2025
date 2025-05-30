import random
import time
import json
from locust import HttpUser, task, between
from faker import Faker

fake = Faker()

# Book inventory with stock levels
BOOK_INVENTORY = {
    "Book A": 100,
    "Book B": 75,
    "Book C": 50,
    "Book D": 25,
    "Book E": 10,
    "Book F": 1,
    "Harry Potter": 200,
    "The Great Gatsby": 150,
    "To Kill a Mockingbird": 120,
    "1984": 80,
    "Pride and Prejudice": 90,
}

# Different customer profiles for realistic testing
CUSTOMER_PROFILES = [
    {"name": "John Doe", "email": "john.doe@example.com", "card": "6011111111111117"},
    {
        "name": "Jane Smith",
        "email": "jane.smith@example.com",
        "card": "4111111111111111",
    },
    {
        "name": "Bob Johnson",
        "email": "bob.johnson@example.com",
        "card": "5555555555554444",
    },
    {
        "name": "Alice Brown",
        "email": "alice.brown@example.com",
        "card": "378282246310005",
    },
    {
        "name": "Charlie Wilson",
        "email": "charlie.wilson@example.com",
        "card": "6011111111111117",
    },
]

# Fraudulent patterns (for mixed scenario testing)
FRAUDULENT_PATTERNS = [
    {"card": "0000000000000000", "reason": "invalid_card"},
    {"card": "1234567890123456", "reason": "test_card"},
    {"email": "fraud@suspicious.ru", "reason": "suspicious_email"},
    {"email": "fraud@suspicious.test", "reason": "fake_email"},
    {"amount_multiplier": 100, "reason": "high_amount"},  # Order 100x normal quantity
]


class BaseBookstoreUser(HttpUser):
    wait_time = between(1, 3)  # Wait 1-3 seconds between requests

    def on_start(self):
        """Initialize user session"""
        self.customer = random.choice(CUSTOMER_PROFILES)
        self.order_history = []

    def create_base_order_payload(self, items, customer_override=None):
        """Create base order payload"""
        customer = customer_override or self.customer

        return {
            "user": {"name": customer["name"], "contact": customer["email"]},
            "creditCard": {
                "number": customer["card"],
                "expirationDate": "12/25",
                "cvv": "123",
            },
            "userComment": fake.sentence(),
            "items": items,
            "billingAddress": {
                "street": fake.street_address(),
                "city": fake.city(),
                "state": fake.state_abbr(),
                "zip": fake.zipcode(),
                "country": "USA",
            },
            "shippingMethod": random.choice(["Standard", "Express", "Overnight"]),
            "giftWrapping": random.choice([True, False]),
            "termsAndConditionsAccepted": True,
            "notificationPreferences": ["Email"],
            "device": {"type": "Desktop", "model": "Browser", "os": fake.user_agent()},
            "browser": {"name": "Chrome", "version": "1.0"},
            "appVersion": "1.0.0",
            "screenResolution": "1920x1080",
            "referrer": "Direct",
            "deviceLanguage": "en-US",
        }

    def submit_order(self, payload, scenario_name="default"):
        """Submit order and track response"""
        with self.client.post(
            "/v2/checkout",
            json=payload,
            catch_response=True,
            name=f"checkout_{scenario_name}",
        ) as response:
            if response.status_code == 200:
                data = response.json()
                order_id = data.get("orderId")

                if order_id:
                    self.order_history.append(
                        {
                            "order_id": order_id,
                            "items": payload["items"],
                            "timestamp": time.time(),
                        }
                    )

                    # Poll for order status (with low frequency)
                    if random.random() < 0.5:  # 50% chance to poll
                        time.sleep(random.uniform(1.5, 2.5))
                        self.poll_order_status(order_id, scenario_name)

                    response.success()
                else:
                    response.failure("No order ID returned")
            else:
                response.failure(f"Status: {response.status_code}")

    def poll_order_status(self, order_id, scenario_name="default"):
        """Poll order status (lightweight)"""
        with self.client.get(
            f"/v2/orders/{order_id}",
            catch_response=True,
            name=f"poll_status_{scenario_name}",
        ) as response:
            if response.status_code == 200:
                data = response.json()
                status = data.get("status", "UNKNOWN")

                if status in ["Order Approved", "Order Rejected"]:
                    response.success()
                elif status == "PENDING":
                    response.success()  # Still processing, that's ok
                else:
                    response.failure(f"Unexpected status: {status}")
            else:
                response.failure(f"Status: {response.status_code}")


class NonConflictingOrdersUser(BaseBookstoreUser):
    """Scenario 1: Multiple non-fraudulent, non-conflicting orders"""

    @task(3)
    def order_different_books(self):
        """Order different books to avoid conflicts"""
        # Select 1-3 different books with good stock levels
        available_books = [book for book, stock in BOOK_INVENTORY.items() if stock > 10]
        selected_books = random.sample(
            available_books, min(random.randint(1, 3), len(available_books))
        )

        items = []
        for book in selected_books:
            # Order small quantities to avoid stock conflicts
            max_qty = min(3, BOOK_INVENTORY[book] // 10)  # Max 3 or 10% of stock
            quantity = random.randint(1, max_qty)

            items.append({"name": book, "quantity": quantity})

        payload = self.create_base_order_payload(items)
        self.submit_order(payload, "non_conflicting")

        # Add small delay to simulate realistic user behavior
        time.sleep(random.uniform(0.5, 2.0))

    @task(1)
    def order_high_stock_books(self):
        """Order from high-stock books only"""
        high_stock_books = [
            book for book, stock in BOOK_INVENTORY.items() if stock > 50
        ]
        selected_book = random.choice(high_stock_books)

        items = [
            {
                "name": selected_book,
                "quantity": random.randint(1, 5),
            }
        ]

        payload = self.create_base_order_payload(items)
        self.submit_order(payload, "high_stock")


class MixedOrdersUser(BaseBookstoreUser):
    """Scenario 2: Mix of fraudulent and non-fraudulent orders"""

    @task(7)  # 70% legitimate orders
    def legitimate_order(self):
        """Submit legitimate order"""
        books = random.sample(list(BOOK_INVENTORY.keys()), random.randint(1, 2))

        items = []
        for book in books:
            items.append(
                {
                    "name": book,
                    "quantity": random.randint(1, 3),
                }
            )

        payload = self.create_base_order_payload(items)
        self.submit_order(payload, "legitimate")

    @task(3)  # 30% fraudulent orders
    def fraudulent_order(self):
        """Submit potentially fraudulent order"""
        fraud_pattern = random.choice(FRAUDULENT_PATTERNS)

        # Create fraudulent customer profile
        fraudulent_customer = self.customer.copy()

        if "card" in fraud_pattern:
            fraudulent_customer["card"] = fraud_pattern["card"]
        if "email" in fraud_pattern:
            fraudulent_customer["email"] = fraud_pattern["email"]

        # Create items
        books = random.sample(list(BOOK_INVENTORY.keys()), random.randint(1, 2))
        items = []

        for book in books:
            base_quantity = random.randint(1, 2)
            # Apply fraud multiplier if specified
            if "amount_multiplier" in fraud_pattern:
                base_quantity *= fraud_pattern["amount_multiplier"]

            items.append(
                {
                    "name": book,
                    "quantity": base_quantity,
                }
            )

        payload = self.create_base_order_payload(items, fraudulent_customer)

        # Mark as fraudulent attempt for tracking
        with self.client.post(
            "/v2/checkout",
            json=payload,
            catch_response=True,
            name="checkout_fraudulent",
        ) as response:
            # Both success and failure are valid outcomes for fraud testing
            if response.status_code in [200, 400]:
                if response.status_code == 400:
                    # Expected fraud rejection
                    data = response.json()
                    if "fraud" in data.get("error", {}).get("message", "").lower():
                        response.success()
                    else:
                        response.failure("Expected fraud rejection")
                else:
                    # Fraud passed through (might be valid depending on your rules)
                    response.success()
            else:
                response.failure(f"Unexpected status: {response.status_code}")


class ConflictingOrdersUser(BaseBookstoreUser):
    """Scenario 3: Conflicting orders (same books simultaneously)"""

    @task(5)
    def order_limited_stock_books(self):
        """Order books with limited stock to create conflicts"""
        # Focus on low-stock books
        low_stock_books = [
            book for book, stock in BOOK_INVENTORY.items() if stock <= 25
        ]
        selected_book = random.choice(low_stock_books)

        # Order quantity that might cause conflicts
        stock_level = BOOK_INVENTORY[selected_book]
        # Order between 20-80% of available stock
        min_qty = max(1, stock_level // 5)  # 20% of stock
        max_qty = max(min_qty, (stock_level * 4) // 5)  # 80% of stock
        quantity = random.randint(min_qty, max_qty)

        items = [
            {
                "name": selected_book,
                "quantity": quantity,
            }
        ]

        payload = self.create_base_order_payload(items)
        self.submit_order(payload, "conflicting")

    @task(3)
    def order_book_f(self):
        """Specifically target Book F (only 1 in stock)"""
        items = [
            {
                "name": "Book F",
                "quantity": 1,
            }
        ]

        payload = self.create_base_order_payload(items)
        self.submit_order(payload, "book_f_conflict")

    @task(2)
    def order_multiple_conflicting(self):
        """Order multiple low-stock books"""
        low_stock_books = [
            book for book, stock in BOOK_INVENTORY.items() if stock <= 50
        ]
        selected_books = random.sample(low_stock_books, min(3, len(low_stock_books)))

        items = []
        for book in selected_books:
            stock_level = BOOK_INVENTORY[book]
            # Order significant portion of stock
            quantity = max(1, stock_level // 3)

            items.append(
                {
                    "name": book,
                    "quantity": quantity,
                }
            )

        payload = self.create_base_order_payload(items)
        self.submit_order(payload, "multiple_conflicting")

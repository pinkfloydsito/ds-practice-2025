# 📎 Order Executor Working

```
┌──────────────┐     gRPC     ┌────────────────────┐
│ Order Queue  ├────────────▶│  Order Executor     │
└──────────────┘             │  (replicated)       │
                             └──────┬──────────────┘
                                    │
                                    │ gRPC
       ┌────────────────────────────┼────────────────────────────┐
       │                            │                            │
┌───────────────┐         ┌────────────────────┐       ┌────────────────────┐
│ fraud_detection│◀──────▶│ transaction_verif. │◀────▶│    suggestions      │
└───────────────┘         └────────────────────┘       └────────────────────┘
```

### Keeping Orchestrator and Order Executor separate:
1. `orchestrator` is for HTTP requests from frontend.
2. `order_executor` is for background tasks, handled internally in the system.

```
[Frontend Browser] ---> [Orchestrator (Flask)] ---> [Microservices via gRPC]

[Background System / Queue] ---> [Order Executor (Worker)] ---> [Microservices via gRPC]
```

### Dequeues
```
              [ Order Queue ] ← shared (e.g., Redis)
                    ↑
          ┌─────────▼─────────┐
          │                   │
   [order_executor_1]   [order_executor_2]
        (Leader)            (Follower)
          │
     Dequeues + Executes
```

# 📜 Project Documentation

This document explains the architecture and inner workings of the order-processing system involving multiple microservices, Redis-based leader election, the system model and vector clocks.

---

## 🕉 System Model

### 📦 Architecture Type
- **Architecture**: Microservice-based architecture
- **Communication**: Services interact via gRPC
- **Coordination**: Leader election and job coordination via Redis

### 🔗 Components
- **Order Executor**: Multiple replicas, one elected as leader to handle orders.
- **Redis**: Centralized coordination for:
  - Leader election (via `SETNX` pattern)
  - Order queue (`LPUSH`/`LPOP`)
- **Fraud Detection Service**: Validates the legitimacy of an order.
- **Transaction Verification Service**: Verifies payment details.
- **Suggestion Service**: Recommends related books for the order.
- **PostgreSQL**: Stores book and order information.
- **Orchestrator**: Acts as frontend API layer.

### ♻ Flow of Events
1. Client places order via frontend.
2. Order is pushed to Redis queue.
3. OrderExecutor leader pops from queue and dispatches it to the relevant services.
4. Each service responds back with data.
5. Logs are maintained per service for audit/debug.

### 💥 Failure Modes
- **OrderExecutor crash**: Redis automatically allows other replicas to contend for leadership.
- **Redis failure**: Coordination and queue operations halt until Redis is restored.
- **Microservice crash**: gRPC call fails; logged by OrderExecutor and retried/reported.

---

## ♻ Leader Election Diagram

### Algorithm Used: Redis-based lock (`SETNX`)

```
[Initial State]
No leader → All executors try to acquire lock

[Frame 1]
Executor-2 acquires lock:
  Redis key: leader_lock = Executor-2
  Logs: [Executor-2] Became leader

[Frame 2]
Executor-1, Executor-3:
  Check Redis → Not leader
  Logs: [Executor-X] Not leader. Waiting...

[Frame 3]
Executor-2 renews the lock every 10 seconds
If it crashes, key expires → New election happens
```

---

## ⏱ Vector Clocks Diagram

### Scenario: Order is placed and processed through services

```
![Vector Clock Diagram](./images/vector-clock.final.png)
```

Each number represents the logical clock of that process. Vector clock updates ensure causality and ordering.

---
## System Model

The system model for the **Bookstore** is a distributed microservices architecture designed to manage the order checkout process.

---

### 🧩 Components

- **Order Orchestrator**: Coordinates workflows across services, manages concurrency, and handles error propagation.
- **Transaction Service**: Validates billing information and credit card details.
- **Fraud Service**: Performs fraud detection checks on orders.
- **Suggestions Service**: Generates book recommendations post-validation.
- **Order Event Tracker**: Maintains a vector clock for event ordering and consistency across distributed services.
- **Order Executor**: Queues and dequeues orders, ensuring that the leader executor handles the order processing.

---

### 🔀 Concurrency Model

#### Parallel Execution
- Utilizes `ThreadPoolExecutor` to run billing, card, and fraud checks concurrently.

#### Dependency Management
- **Billing Check**: Runs first.
- **Card Check**: Depends on billing; starts only after billing completes.
- **Fraud Check**: Runs in parallel with billing and card checks.
- **Suggestions**: Fetched only after fraud and card checks both succeed.

#### Early Termination
- Errors in any check (e.g., invalid billing) trigger cancellation of non-essential tasks via `early_termination` events.

---

### 📈 Data Flow

#### Initialization
- Order, user, credit card, and billing data are propagated to all services via `initialize_services`.

#### Processing
- Each service receives specific parameters (e.g., `check_card` receives credit card details).

#### Cleanup
- `broadcast_clear_order` ensures all services delete temporary order data using a final vector clock.

---

### ⚠️ Error Handling

- Errors in any service (e.g., failed fraud check) are aggregated and propagated to the orchestrator.
- Failed checks trigger immediate termination of dependent tasks using a flag.
  - Specially ensuring that **suggestions service** calls are skipped if fraud check fails.

---

### ⏱️ Vector Clocks

- Track event ordering across services to maintain consistency.
- Final clock state is broadcast during cleanup to ensure all services agree on event timelines.

---

### 🔗 Inter-Service Communication

- Uses **gRPC** for cross-service calls (via `grpc_factory` initialization).
- Services are **decoupled**; orchestrator and the order executor act as the central coordinator at the moment (in the future execution will be fully done by the order executor).

---

### 📦 Order Processing Workflow

1. **Initialization**: Services are set up with order data.
2. **Concurrent Checks**:
   - Billing validation → Credit card check (sequential)
   - Fraud detection (parallel to billing/card)
3. **Post-Validation**:
   - Suggestions fetched only if all prior checks succeed.
4. **Cleanup**:
   - Data is cleared across services atomically.

---

## 🧵 Threading & Synchronization

- Uses `threading.Event` and `as_completed` to manage task dependencies.
- Global `results` dictionary with thread locks ensures safe concurrent data access.
## 📌 Notes
- Vector clocks and leader election are simplified representations based on lecture models.
- gRPC ensures reliable structured communication.
- Redis lock + TTL gives fault tolerance during leadership handoff.
- Microservices are loosely coupled and easily scalable.

---

## 📂 Directory Reference
```
/utils/pb/*                  ← Generated gRPC protobufs
/order_executor/src/app.py  ← Leader election and dispatcher
/order_executor/src/debug.py← Flask-based debug server
/fraud_detection/src/*      ← Fraud analysis logic
/suggestions/src/*          ← Book recommendation engine
/transaction_verification/src/* ← Payment check logic
/orchestrator/src/*         ← Main API handler
```


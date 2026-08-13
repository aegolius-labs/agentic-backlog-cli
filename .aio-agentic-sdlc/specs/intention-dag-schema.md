# Intention DAG Schema Specification

## 1. Overview & Purpose
The Intention DAG Schema is a structural blueprint designed to map the desired architectural state of software systems. By fusing concepts from the **C4 Model** (Structural Levels), **Domain-Driven Design (DDD)** (Bounded Contexts), and **OpenAPI** (Interfaces), this schema provides a deterministic, machine-readable language for agents and developers to reason about architecture. 

It defines a system as a Directed Acyclic Graph (DAG) of architectural intents, where **Nodes** represent structural entities (from entire systems down to specific endpoints) and **Edges** define the relationships, dependencies, and communication flow between them.

## 2. Core Concepts
- **Nodes**: The building blocks of the architecture. They can range from coarse-grained concepts (Systems, Containers) to fine-grained elements (Modules, Components, Endpoints, Entities).
- **Edges**: The relationships connecting nodes. They define composition (e.g., a Container *contains* a Module), dependency (a Component *depends_on* another), and interaction patterns (*calls*, *reads*, *writes*).
- **Domains (Bounded Contexts)**: Categorize nodes into specific business domains (as per DDD), providing logical boundaries and preventing tight coupling between disparate parts of the system.

## 3. JSON Schema Specification

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "metadata": { 
      "type": "object", 
      "properties": { 
        "name": {"type": "string"}, 
        "version": {"type": "string"} 
      } 
    },
    "nodes": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": { "type": "string" },
          "type": { "enum": ["system", "container", "module", "component", "endpoint", "entity"] },
          "domain": { "type": "string", "description": "DDD Bounded Context" },
          "name": { "type": "string" },
          "description": { "type": "string" },
          "attributes": { "type": "object", "description": "Specifics like Tech stack, HTTP methods, OpenAPI spec refs" }
        },
        "required": ["id", "type", "name"]
      }
    },
    "edges": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "source": { "type": "string" },
          "target": { "type": "string" },
          "type": { "enum": ["contains", "depends_on", "calls", "publishes", "subscribes", "reads", "writes", "implements"] },
          "description": { "type": "string" }
        },
        "required": ["source", "target", "type"]
      }
    }
  },
  "required": ["metadata", "nodes", "edges"]
}
```

## 4. Node Definitions
Nodes represent structural elements in the Intention DAG.

- **`system`**: The highest level of abstraction (C4 System Context). Represents the entire software system being modeled.
- **`container`**: An executable or deployable unit (C4 Container), such as a web application, mobile app, or database.
- **`module`**: A logical grouping of components within a container, often aligning with a DDD Bounded Context.
- **`component`**: A building block within a module (C4 Component). E.g., a specific service, controller, or repository.
- **`endpoint`**: Represents a specific API or interface boundary (OpenAPI alignment). E.g., a REST API endpoint or a gRPC method.
- **`entity`**: A domain object, data model, or schema definition.

## 5. Edge Definitions
Edges define how nodes interact and relate to each other.

- **`contains`**: Represents a structural hierarchy (e.g., System contains Container, Module contains Component).
- **`depends_on`**: A generic dependency where the source requires the target to function.
- **`calls`**: Synchronous communication or method invocation (e.g., API Gateway calls Service).
- **`publishes` / `subscribes`**: Asynchronous, event-driven communication via message brokers.
- **`reads` / `writes`**: Data flow interactions, typically between a component and a datastore/entity.
- **`implements`**: Denotes that a component implements a specific interface or endpoint contract.

## 6. Constraints & Validation
To maintain architectural integrity, the Intention DAG enforces the following constraints:
1. **Hierarchical Tree (Composition)**: The `contains` edges must form a strict tree structure without cycles. A node can only have one parent.
2. **Acyclic Dependencies**: The `depends_on` and `calls` edges must form a Directed Acyclic Graph (DAG) to prevent circular dependencies between components and modules.
3. **Domain Integrity**: Cross-domain calls should ideally happen at the Container or Module level, restricting deep component-to-component coupling across Bounded Contexts.

## 7. Reference YAML Example
Below is an example mapping of a typical 3-tier architecture (UI -> API -> Model -> DB) using the Intention DAG Schema.

```yaml
metadata:
  name: "E-Commerce System"
  version: "1.0.0"

nodes:
  # Containers
  - id: "ui-web"
    type: "container"
    domain: "storefront"
    name: "Web Storefront"
    description: "Customer facing web application"
    attributes:
      tech_stack: "React, TypeScript"

  - id: "api-gateway"
    type: "container"
    domain: "gateway"
    name: "API Gateway"
    description: "Main entrypoint for client requests"
    attributes:
      tech_stack: "Node.js, Express"

  - id: "catalog-service"
    type: "container"
    domain: "catalog"
    name: "Catalog Service"
    description: "Manages product catalog"
    attributes:
      tech_stack: "Go"

  - id: "catalog-db"
    type: "container"
    domain: "catalog"
    name: "Catalog Database"
    description: "Stores product data"
    attributes:
      tech_stack: "PostgreSQL"

  # Components
  - id: "product-controller"
    type: "component"
    domain: "catalog"
    name: "Product Controller"
    description: "Handles product related HTTP requests"
  
  - id: "product-repository"
    type: "component"
    domain: "catalog"
    name: "Product Repository"
    description: "Data access layer for products"

  # Entities / Endpoints
  - id: "get-products-endpoint"
    type: "endpoint"
    domain: "catalog"
    name: "GET /products"
    attributes:
      method: "GET"
      path: "/products"
      
  - id: "product-entity"
    type: "entity"
    domain: "catalog"
    name: "Product"

edges:
  # Composition
  - source: "catalog-service"
    target: "product-controller"
    type: "contains"
  - source: "catalog-service"
    target: "product-repository"
    type: "contains"
  
  # Dependencies / Flow
  - source: "ui-web"
    target: "api-gateway"
    type: "calls"
    description: "Fetches data for UI"
  
  - source: "api-gateway"
    target: "catalog-service"
    type: "calls"
    description: "Routes catalog requests"

  - source: "product-controller"
    target: "get-products-endpoint"
    type: "implements"

  - source: "product-controller"
    target: "product-repository"
    type: "depends_on"

  - source: "product-repository"
    target: "product-entity"
    type: "reads"

  - source: "product-repository"
    target: "catalog-db"
    type: "reads"
    description: "Executes queries against DB"
```

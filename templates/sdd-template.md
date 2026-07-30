---
document_type: sdd
title: "{{ title }}"
author: "{{ author }}"
date: "{{ date }}"
related_prd: "{{ related_prd }}"
{% if node_id is defined %}node_id: "{{ node_id }}"
{% endif %}
---
# {{ title }}

## 1. Architecture Overview

{{ architecture_overview }}

## 2. System Components

{{ system_components }}

## 3. Data Model

{{ data_model }}

## 4. API Design

{{ api_design }}

## 5. Security Considerations

{{ security_considerations }}

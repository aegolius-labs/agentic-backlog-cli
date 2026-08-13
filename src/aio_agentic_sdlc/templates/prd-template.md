---
document_type: prd
title: "{{ title }}"
author: "{{ author }}"
date: "{{ date }}"
status: "{{ status | default('Valid - Unprocessed') }}"
---
# {{ title }}

## 1. Introduction

{{ introduction }}

## 2. Objectives

{{ objectives }}

## 3. Scope

{{ scope }}

## 4. Requirements

{{ requirements }}

## 5. User Stories

{{ user_stories }}

## 6. Success Metrics

{{ success_metrics }}

## 7. Dependencies

{{ dependencies }}

## 8. Non-Functional Requirements

{{ non_functional_requirements }}

## 9. Out of Scope

{{ out_of_scope }}

## 10. Viability Research

{{ viability_research }}

## 11. Changelog

{{ changelog }}

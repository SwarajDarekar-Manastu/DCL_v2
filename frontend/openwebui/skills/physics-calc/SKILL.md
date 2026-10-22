---
name: Physics calculation
description: A propulsion calculation done by a deterministic calculator, never by the language model.
intents: [physics_calc]
tools: [physics_calculator]
---

# Physics calculation

A propulsion calculation done by a deterministic calculator, never by the language model.

## When to use

"Mass flow for 5 N at Isp 225 s?", "CEA performance of 90% HTP at 10 bar, expansion ratio 50"

## What the engine does

1. Read the operation and the values with their units from the question.
2. Run the calculator: unit conversion, mass flow from thrust, isentropic sizing, CEA performance, thruster scaling.
3. Answer with the result, its unit and the inputs used, labelled as a calculation.

## Tools

`physics_calculator`

## Limits

- Missing inputs are reported, not assumed.

Every number in the answer comes from a tool result and is checked before it is shown; each cited source carries its provenance label.

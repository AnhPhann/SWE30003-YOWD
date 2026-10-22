# Team handoff

The local files provide a runnable starting point for the team. Review the workflow, sample policies and code together before agreeing final ownership. The main workflow already exists; the work below covers requirement gaps, improvements, verification and the assessed report.

## Team members

Names and Discord handles are verified against the submitted A2 contribution document, page 3:

- Anh Phan: Chip.
- Domenic Sesa: domirox.
- Hoa Phat Thai: flashman.
- Patrick Lunney: PL.

## Permission for Git and sharing actions

An assistant must not stage files, create commits, push, publish, upload, create pull requests or change sharing settings without Anh's explicit permission for that action. Permission to edit local files does not grant permission for any of those actions. Human members use the group's agreed Git workflow.

## First joint review

1. Run `python run.py --demo` and the test suite described in the README.
2. Open the desktop application and complete one request from lodgement to delivery. Review failed pickup, pending payment authorisation, unsuccessful allocation and failed delivery as well.
3. Agree whether to keep or revise the sample service suburbs, tariff, quote-window policy, business trading hours and all-or-nothing parcel handling.
4. Agree ownership of the public methods, UI actions and saved data affected by each feature. Coordinate changes to DeliveryRequest because several workflows call it.
5. Record agreed changes in `DESIGN_DECISIONS.md`, with code and tests that demonstrate the result.

## Suggested feature ownership

This is a proposed split based on the team's earlier A2 areas. It is not a claim that the group has agreed to it or that a member has already completed the work. Everyone should contribute implementation, tests, demonstration evidence and their own design/reflection material.

### Anh Phan / Chip: customer and request workflow

Main files: `models/customer.py`, `models/parcel.py`, request creation/quote-response actions in `application.py`, and `NewRequestDialog` in `ui.py`.

1. Add complete pickup and destination addresses while keeping suburb/zone values separate for service-area validation and quotation. Coordinate the field contract with Domenic and Patrick before changing shared data.
2. Ensure addresses appear in request details and survive save/reopen. Implement and test the serialization fields for these changes.
3. Review input correction and parcel removal. An edit-selected-parcel action is an optional usability improvement; cancellation must continue to save nothing.
4. Add regression tests and capture the request scenario: empty form, invalid input, correction/removal, valid multiple parcels, unsupported area and quote acceptance/decline.
5. Supply the introduction/scope and customer/request detailed design, A2 evaluation and lessons. Assemble the final report from each member's completed sections, including the complete A2 appendix.

Completion: a user can lodge a request with usable addresses, correct input and reopen the saved details without losing data. Report assembly means combining, numbering and formatting supplied sections; Anh is not responsible for writing everyone else's material.

### Domenic Sesa / domirox: quotation, pickup and payment

Main files: `models/delivery_quote.py`, `models/payment_record.py`, `pricing.py`, and quotation/pickup/payment actions in `application.py` and `ui.py`.

1. Agree the existing sample tariff and time-estimation rules with the group. Retain or revise them with an explanation and exact expected-price/window tests. Quote creation must remain separate from allocation.
2. Add a specific failed-pickup reason through the interface, application and request model. Distinguish missing/mismatched parcels and customer absence instead of storing the same generic message for every failure. Preserve the recorded reason after restart.
3. Review the existing payment flow and feedback: mismatch awaiting authorisation, authorisation recorded but pickup awaiting confirmation, and completed pickup. Test wrong reporters, invalid authorisation details and attempted payment replacement.
4. Capture the pickup/payment scenario and supply its detailed design, A2 evaluation and lessons. Explain how the implemented authorisation rule resolves the earlier inconsistency.
5. Integrate the detailed class diagram from each owner's supplied attributes, operations and relationships. Independently test Patrick's executable on another computer and report actual results.

Completion: quotation rules are agreed and testable; failed pickup records the actual reason without creating a payment; pending payment cannot incorrectly complete collection. Diagram integration does not mean discovering or writing other members' class details for them.

### Hoa Phat Thai / flashman: staff and allocation

Main files: `models/staff_list.py`, `models/delivery_staff.py`, `models/availability_schedule.py`, `models/delivery_assignment.py`, and staff/allocation actions in `application.py` and `ui.py`.

1. Improve availability editing by displaying existing periods and making changes/removal explicit. Invalid edits and cancellation must preserve the original schedule. Removing the current three-period form limit is optional.
2. Improve allocation feedback by showing the quoted window and worker eligibility. Keep authoritative active-status and full-window coverage checks in the business layer.
3. Agree trading-hours behaviour with Domenic and the group; implement and test the agreed scheduling constraints. Worker availability alone does not define the business operating calendar.
4. Extend meaningful boundary tests and capture the staff/allocation scenario, including invalid periods, inactive/unavailable workers, duplicate allocation rejection and successful allocation. Preserve the agreed overlapping-job rule and retained history.
5. Supply staff/allocation design, A2 evaluation and lessons, and lead the architecture explanation. Coordinate the final consistency review; every owner checks and corrects their own code, diagram details and scenarios.

Completion: schedules can be maintained without accidental data loss; allocation feedback is clear; rejected actions leave the request unchanged. Hoa coordinates the final review rather than being responsible for repairing everyone's work.

### Patrick Lunney / PL: delivery outcomes, restoration and packaging

Main files: delivery-outcome actions in `models/delivery_request.py` and `application.py`, `models/delivery_statistics.py`, `serialization.py`, `storage.py`, and `__main__.py`.

1. Improve history presentation with pickup and assignment start/end times. Verify successful/failed delivery, payment retention and Return required flags without claiming that depot return is already complete.
2. Make statistics readable using worker names, IDs and former-worker status. Preserve inclusive completion-date counting and empty-period zeroes. Date presets are an optional presentation improvement after the required workflow is complete.
3. Verify one mixed-state database across restart, including multiple request states, a retried assignment and a former worker. Each feature owner supplies and tests their own saved fields; Patrick integrates the complete graph.
4. Prepare a writable persistent default data location, retain the explicit database-path option, and build the executable with reproducible instructions. Coordinate with Domenic for an independent packaged-run check.
5. Capture delivery/restoration evidence and supply the bootstrap, persistence, deployment and conclusion material, plus the relevant detailed design, A2 evaluation and lessons.

Completion: delivery history/statistics remain correct after restart, and the executable launches and saves reliably using documented instructions. Patrick does not inherit all serialization work or sole responsibility for testing the packaged program.

## Shared work and workload balance

- Everyone owns one connected feature area, its interface changes, relevant persistence fields, tests, execution evidence, detailed-design explanation, A2 evaluation and lessons.
- Anh assembles completed report sections; each member delivers their own finished content and figures.
- Domenic integrates the class diagram; each owner supplies and verifies their implemented class details.
- Hoa coordinates consistency review; each owner resolves findings in their area.
- Patrick builds the executable; Domenic independently tests it, and all owners check their own workflows in the final package.
- Assign reviewers across feature boundaries: Hoa reviews Anh's request/allocation handover; Anh reviews Domenic's quote/pickup flow; Patrick reviews Hoa's assignment/history changes; Domenic reviews Patrick's payment retention and packaged-run behaviour.
- Review actual progress after the first agreed change from each owner. Reassign substantial blockers if one member's work proves heavier. Do not add unnecessary features or invent hours to make workloads appear equal.

Coordinate shared-file edits by method: Anh owns request creation/quote responses, Domenic quotation/pickup/payment, Hoa staff/allocation, and Patrick delivery/reporting/restoration. Changes to `DeliveryRequest`, `application.py`, `ui.py` and `serialization.py` need integration review; avoid whole-file replacements that discard another member's work.

## Meaningful work still available

The starter implements the basic workflow rather than leaving empty class stubs. Team contributions can improve and justify the real behaviour:

- Expand suburb-only input to street-level addresses while keeping service-area validation separate from display text.
- Replace the demonstration tariff and timing assumptions with an agreed policy, then update examples, tests and design justification together.
- Record specific failed-pickup reasons and resolve business trading-hours behaviour.
- Review empty-state guidance, field validation, status messages and the visibility of pending authorisation.
- Improve availability maintenance and request-detail presentation using feedback from another member.
- Review the snapshot design against the chosen scope and implement a relational alternative only if the group can justify and test the added work.
- Package and verify the application on another computer.
- Capture actual evidence and write a reflection supported by code changes and observed results.

Do not introduce partial parcel outcomes, authentication or route optimisation by accident through a screen change. Agree their rules and detailed-design impact first if the group chooses to include them.

## Report outline aligned to the assessment

1. **Introduction and implementation scope.** Describe the supported business areas, interface and explicit scope boundaries.
2. **Detailed object-oriented design: 30 points.** Show the final detailed class diagram, attributes/operations, changed and retained responsibilities, startup/restoration, interaction scenarios, interface and persistence support. Justify significant changes and important non-changes.
3. **Evaluation of the original design: 20 points.** Use specific A2 assumptions, CRC responsibilities and scenario conflicts to explain what worked, what was missing and what implementation exposed.
4. **Lessons learned: 10 points.** Explain what the group would do differently when producing another initial object design, supported by its actual experience.
5. **Architecture styles: 10 points.** Identify the implemented components, connections and constraints above the individual-class level. Verify the claimed dependency rules against the source.
6. **Implementation and execution evidence: 50 points.** State the environment and coding standard, explain how to run the final package, and provide actual evidence for valid/invalid input, correction/deletion and completed business outcomes.
7. **Conclusion and references.** Summarise the implemented scope and remaining material limitations. Include only sources used in the report.
8. **Appendix A: complete submitted A2 report.** Attach the full A2 submission rather than replacing it with a summary or link.

The source/executable deliverable, required signed cover sheet and contribution document also need to be prepared. This starter documentation does not replace those submission items.

## Evidence each member should supply

For every owned workflow, record the starting state, input, observed output and final stored state. Include successful execution and at least one rejected operation that leaves the previous business state intact. Keep the actual input values visible in screenshots or a narrated demonstration so another person can follow the evidence.

Run the full suite after integration and record the command and actual result. Do not claim a build, screenshot, package or test result that the team has not produced and reviewed.

Keep a short contribution log with the date, work performed, relevant files, review/testing and actual time spent. Resolve ownership descriptions with the team. Do not invent another member's hours or reduce them solely to reflect a judgement about effort.

## Final handoff check

- The agreed business areas work across the integrated application.
- The report's class names, attributes, operations and multiplicities match the final code.
- The report distinguishes real implemented behaviour from sample policy assumptions.
- The run instructions work on another member's computer.
- Execution evidence corresponds to the final package.
- The full A2 report is attached and required submission documents are complete.
- Anh and the group decide when and where to publish, share or submit.
- No assistant performs staging, commits, pushes, publishing or uploads without Anh's explicit permission.

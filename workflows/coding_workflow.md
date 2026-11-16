# Coding Workflow

This document defines how Claude builds a tool for you. Follow the stages in order. Do not skip ahead.

## Language

Python, unless the user says otherwise.

## Stage 1: Clarify

Before planning, ask questions about:

- **Purpose:** What problem does the tool solve?
- **Users:** Who will run it, and how technical are they?
- **Inputs and outputs:** What data goes in, and what should come out?
- **Key features:** Which features are must-have, and which are nice-to-have?
- **Constraints:** Data sources, file formats, deadlines, or anything the tool must not do.

Do not start planning until the user has answered.

## Stage 2: Plan

Write a short plan covering:

- **Objective:** One sentence on what the tool does.
- **Features:** A must-have list and a nice-to-have list.
- **Structure:** The main parts of the code, explained in plain terms.
- **Test approach:** What will be tested and how.
- **Risks and open questions:** Anything that could change the design.

Wait for the user's approval before building. If the user asks for changes, update the plan and wait again.

## Stage 3: Build

- Build the tool in `drafts/` while work is in progress.
- Keep the code simple. Explain each part in plain language.
- Use clear names for files, functions, and variables.
- Follow the file naming rules in CLAUDE.md.

## Stage 4: Test

- Test every function with normal inputs, edge cases (empty, zero, very large, or unusual values), and bad inputs.
- Run the full tool from start to finish on a sample input.
- Check results against values worked out by hand or with an independent calculation.

## Stage 5: Quality check

The tool passes only when all of the following are true:

1. Every function has tests covering normal, edge, and bad inputs.
2. Test coverage is at least 90%.
3. Zero failing tests and zero warnings.
4. The code passes a linter (an automatic style and error checker).
5. The full tool runs end to end, and its output matches the independently checked values.
6. Bad input produces a clear error message, not a crash.
7. A final review pass reads the code for bugs. Any fix triggers a full re-run of every test.
8. The README's commands are run exactly as written and work.

If any item fails, fix it and rerun all checks. Do not save the tool until all eight items pass.

## Stage 6: Save

Once the quality check passes, save the tool to `outputs/<tool_name>/` containing:

- The code files
- A README explaining what the tool does, how to install it, and how to run it

Test results are not saved to the output folder. They are reported in the chat.

## Reporting

In the chat, report:

- Each of the eight quality check items as pass or fail, with the actual output or evidence
- Any bugs found and how they were fixed
- Anything not verified, and why

Report results faithfully. If something failed, say so with the output.

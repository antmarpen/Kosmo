import { test } from '@playwright/test';

// P2-18 design-only placeholders. Replace skips with executable journeys after
// the phase-2 UI/API contracts exist. See docs/specs/phase-2-test-design.md.
test.skip('AC-P2-01 provider onboarding, model discovery, verification, and missing-auth failure', async () => {});
test.skip('AC-P2-02 invalid provider configs show violations and never overwrite valid config', async () => {});
test.skip('AC-P2-03 provider scope choices and unauthorized global scope denial', async () => {});
test.skip('AC-P2-04 create workflow, author nodes, connect, configure, and save draft', async () => {});
test.skip('AC-P2-05 server validation errors render inline on affected nodes', async () => {});
test.skip('AC-P2-06 publish creates next version and activation defaults off', async () => {});
test.skip('AC-P2-07 second author confirms recent publication before overwrite', async () => {});
test.skip('AC-P2-08 runner executes activated Start-Script-AI-End workflow', async () => {});
test.skip('AC-P2-09 editor works at 768/1280 and task views at 375', async () => {});
test.skip('AC-P2-10 all new labels and errors are localized in English and Spanish', async () => {});

test.skip('provider onboarding rejects invalid config, missing auth, and cross-task access', async () => {});
test.skip('provider personal/group/global visibility and non-owner metadata privacy across users', async () => {});
test.skip('workflow editor node selection, deletion, draft reload, and lazy Script editor load', async () => {});
test.skip('Decision and Workflow nodes author correctly; HTTP and Workflow execution fails as unsupported', async () => {});
test.skip('provider/editor controls and validation messages have English-Spanish parity', async () => {});

# AI Test Cases

Use these examples to exercise fraud detection and hybrid matching in the current app.

## Fraud Detection Jobs

### High-risk job

Title:
`URGENT crypto payment assistant needed today only`

Description:
`We need someone immediately for a simple task. Payment will be in USDT or Bitcoin. Click here and go to our external site to get started right now. No contract needed, trust me. This only takes a few minutes and can double your money fast.`

Skills:
`Data Entry, Crypto, Admin Support`

Expected result:
- `High` risk
- Multiple flags for urgency, crypto payment, external redirection, unrealistic claims, and informal scope

### Medium-risk job

Title:
`Quick outreach help for lead list cleanup`

Description:
`Need help ASAP cleaning a sales spreadsheet and contacting prospects. This is a simple task and we want someone who can start immediately. We may move part of the conversation off-platform if things go well.`

Skills:
`Excel, Lead Generation, Communication`

Expected result:
- Usually `Medium` risk
- Flags around urgency, vague scope, and off-platform behavior

### Low-risk job

Title:
`Build a Flask analytics dashboard for internal reporting`

Description:
`We need a freelancer to build an internal analytics dashboard using Flask and PostgreSQL. The project includes user authentication, report filtering, summary cards, and export support. We want clear communication, documented code, and weekly updates.`

Skills:
`Python, Flask, PostgreSQL, Dashboard Design`

Expected result:
- `Low` risk
- Little or no fraud indicators

## Hybrid Matching Tests

Create or edit freelancer profiles so they resemble these profiles.

### Freelancer profile A

Full name:
`Ayesha Khan`

Skills:
`Python, Flask, PostgreSQL, REST API, Dashboards`

Bio:
`Backend engineer focused on Flask apps, analytics dashboards, reporting workflows, API design, and production database work.`

### Freelancer profile B

Full name:
`Bilal Ahmed`

Skills:
`React, UI/UX, JavaScript, CSS`

Bio:
`Frontend specialist for polished interfaces, design systems, and responsive dashboards.`

### Freelancer profile C

Full name:
`Sara Noor`

Skills:
`Machine Learning, NLP, Data Science, Python`

Bio:
`I build semantic search, text similarity, recommendation systems, and model-backed ranking flows for marketplaces.`

## Matching Job Scenarios

### Scenario 1: Exact + semantic fit

Title:
`Escrow marketplace analytics dashboard`

Description:
`Build a reporting dashboard for a freelance escrow platform with Flask, PostgreSQL, charts, filters, authentication, and API endpoints for summary metrics.`

Skills:
`Python, Flask, PostgreSQL, REST API`

What to expect:
- Freelancer profile A should rank highest
- Profile B may get some semantic relevance from dashboard language
- Profile C may get some semantic relevance from platform and ranking language, but should not beat A

### Scenario 2: Semantic fit beyond exact keywords

Title:
`Recommendation and ranking improvements for hiring marketplace`

Description:
`We want to improve how freelancers are ranked for jobs using semantic similarity, profile understanding, text scoring, and recommendation logic.`

Skills:
`Python, Machine Learning, Ranking Systems, NLP`

What to expect:
- Freelancer profile C should rank highest
- A may still appear because of Python
- This is the best case to verify the ML side is influencing ranking, not just exact skill overlap

### Scenario 3: Mixed business + semantic ranking

Title:
`REST API and admin panel for freelancer platform`

Description:
`Need a freelancer to build backend APIs plus an admin interface for internal staff. The work includes authentication, job management, reporting, and workflow cleanup.`

Skills:
`Python, Flask, REST API, Admin Panel`

What to expect:
- A should still rank strongly due to exact backend overlap
- B may score semantically because of admin interface and UI language
- Final order should reflect both semantic relevance and business signals instead of only keyword overlap

## What to Look For in the UI

- Client job detail page:
  `AI Best Matches` now shows `Hybrid`, `Semantic`, and `Skill` components together.
- Freelancer dashboard and jobs list:
  matched jobs now show hybrid score plus the semantic/skill breakdown.
- Fraud test jobs:
  the job card and detail page should show the expected risk badge and reasons.

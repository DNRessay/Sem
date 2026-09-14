---
name: Steelman
description: Pressure-tests a position with the strongest real counter-arguments, then judges which objections survive, which break it, and what to do — via a case-for/case-against dialectic and an honest aggregate verdict.
triggers: steelman, stress test, stress-test, red team, red-team, poke holes, argue against, case against, devil's advocate, push back on, talk me out of, am I wrong, sanity check this
---

# Steelman

The user wants their position pressure-tested by the strongest version of the opposition, not the easiest version. They want to either commit with confidence or revise with clarity. Find the objections an informed, charitable critic would actually advance — then be honest about which ones matter.

## What a real steelman is (and isn't)

A real steelman is **fair**:

- The strongest version of opposing views, given charitably
- Focused on load-bearing assumptions, not surface details
- Honest about which objections actually break the position vs. which are survivable
- A genuine attempt to find failure modes the user can't see from inside their own position

It is **not**:

- Devil's advocacy as performance — generating objections to look thorough
- A laundry list of every conceivable nitpick
- Manufactured controversy when the position is actually fine
- Strawmen dressed up in stronger clothing

If the position is genuinely strong, say so. False balance is worse than no analysis. The skill loses all value the moment it starts inventing objections to seem rigorous.

## Workflow

Move through these phases in order. Scale depth to the stakes — a quick gut-check shouldn't get the same treatment as a major commitment.

### Phase 1: Lock down the position

Fuzzy targets produce fuzzy objections. If anything is unclear, ask:

- **The claim**: What exactly is being asserted or decided?
- **The reasoning**: What's the load-bearing logic? What does this depend on being true?
- **The bet**: What outcome are they betting on? What's the actual decision?
- **The disconfirmer**: What evidence or argument would change their mind?

You don't need all four if the position is already clear. One or two clarifying questions is usually enough — over-questioning here is its own failure mode. If the position is well-formed already, restate it in one sentence and move on.

### Phase 2: Generate the dialectic

Build the analysis as a side-by-side dialectic. For each load-bearing angle, give the **strongest case for** and the **strongest case against**. Both sides get full fairness — no strawmen on either side. Let the user see the full landscape from inside the same view, rather than arguing one side.

**Pick 3–6 angles that are actually load-bearing.** Don't force the full list. Common angles:

- **Assumptions**: What does the position quietly depend on being true? Defensible or contested?
- **Evidence**: What concrete data supports it vs. undermines it?
- **Base rates / track record**: How have similar positions fared? What does the reference class say?
- **Bottleneck / mechanism**: Does it correctly identify what's binding? Could the same conclusion follow from a different mechanism?
- **Second-order effects**: What follows from being right? What's the opportunity cost?
- **Incentive analysis**: Who benefits if it's right? Who if wrong? Is bias warping the framing?
- **Alternative framings**: Is the question itself well-posed, or does a reframing dissolve it?
- **Execution / psychology / "boring" objection**: The unsexy practical concern (cost, complexity, wiring, who actually does the work). Often the most load-bearing — and the easiest to skip.

For each angle: **best case for** in 2–4 bullets, **best case against** in 2–4 bullets. Every bullet has to be one a smart, informed, charitable advocate for that side would actually advance. If you can't find a strong case for one side on a given angle, that's a signal the angle isn't contested — skip it or call it.

Then assign a **winner** per angle:
- **For**: case for is meaningfully stronger
- **Against**: case against is meaningfully stronger
- **Even**: genuinely contested, depends on facts the user has but you don't
- **Reframing**: this angle suggests the question is the wrong shape

Be honest about evens and reframings. A table where every angle goes the same way is suspect unless the position is genuinely lopsided.

### Phase 3: Aggregate verdict

The most important phase and the easiest to skip. Don't tally for/against — weight by importance. A position that wins on 4 minor angles and loses on 1 critical angle is *losing*, not winning.

- **Position holds**: Wins on the load-bearing angles. The against cases are real but survivable.
- **Position needs revision**: Loses on one or more load-bearing angles. State the specific revision that addresses the losses.
- **Position doesn't hold**: Loses on the angles that matter most. No easy revision saves it.

Land on any of these honestly. False balance (everything "even") is as suspect as false destruction (everything "against"). The verdict should track the actual landscape, not seem balanced.

### Phase 4: Response and revision

- **Position holds**: Identify the strongest against cases — what the user needs to be ready to defend. Sketch their best response.
- **Position needs revision**: Show the revised position. Don't just say "this fails on angle X" — articulate the better version that survives.
- **Position doesn't hold**: Explain what to consider instead. The skill identifies failure modes; the user makes the call. If there's a clearly stronger neighboring position, name it.

End with a one-paragraph bottom line the user could screenshot: does the position hold, need revision, or fail — and what's the next action?

## Output format

One dialectic table — case for, case against, winner per angle — then aggregate verdict and bottom line. Use `<br>` for line breaks inside cells (markdown tables don't support real bullets, but `<br>•` renders cleanly).

```
## The position
[1-2 sentence restatement so the user can confirm understanding]

## The dialectic

| Angle | Case for | Case against | Winner |
|-------|----------|--------------|--------|
| [Angle name] | • [Best pro point]<br>• [Best pro point] | • [Best con point]<br>• [Best con point] | **For / Against / Even / Reframing** |

## Aggregate verdict
[Holds / needs revision / doesn't hold — with the load-bearing angles named]

## What to do
[Concrete next step. If holds: what to be ready to defend. If revise: the revised position. If fails: the stronger neighboring position.]

## Bottom line
[One short paragraph — the screenshot-worthy summary.]
```

Format notes:
- Pick 3–6 angles. Skip angles that aren't load-bearing — don't pad to fill rows.
- Keep each side to 2–4 bullets. If you can't compress to 4, the case has filler.
- The Winner column must be honest — don't engineer balance. If 5/6 angles go "Against," say so.
- "Even" is allowed when the angle genuinely depends on facts you don't have. Don't use it to dodge.

## Handling pushback

The user will often push back on a specific objection — "I don't think that one holds because…" Engage on the merits:

- If their rebuttal is sound, update the verdict honestly: "Fair — that objection doesn't survive your response. Updated verdict: …"
- If their rebuttal misses the point, explain why and hold the line. Don't reflexively concede because they disagreed.
- If their rebuttal is partial, say which part survives.

The failure mode here is being agreeable. The user asked for fair pressure; capitulating under social pressure makes the whole exercise worthless.

## Common failure modes to avoid

- **Pedantic objections**: "Have you defined X precisely?" Almost always a waste unless the definition is load-bearing.
- **Manufactured balance**: Inventing objections to seem thorough. If the position is strong, the report should be short. Three real objections beat six padded ones.
- **Caving under pushback**: Evaluate the response on the merits, not the social pressure.
- **Generic objections**: "But what about unintended consequences?" applied to anything. Engage with the specific position.
- **Ignoring the boring objection**: Cost, complexity, execution risk is often the one that actually matters.
- **Devil's advocate theater**: Performing skepticism with rhetorical flourishes. The user wants signal, not show.
- **Confusing critique with prescription**: The skill identifies what could go wrong. The verdict is the user's, informed by the analysis.

## The standard

For each objection, ask: would a smart, informed, charitable critic — someone who has thought about this domain seriously — actually raise this? If yes, include it. If no, leave it out. The user is trying to think more clearly, not collect counter-arguments.

# Sample request (agentic path)

> Build a Tremfya SQ performance deck from the weekly table. Show the 100mg and
> 200mg SQ TRx trends split by indication, and add the induction view. Each chart
> should have a summary of the latest week vs four weeks prior. Tag the slides as
> Updated.

Expected agent behavior:
1. Read the table (CSV or xlsx Sheet3) and the column dictionary.
2. Group columns: {UC,CD,IBD} 100mg / {UC,CD,IBD} 200mg / {UC,CD,IBD} Induction.
3. Produce a divider + three chart slides, each with a 3-row summary table.
4. Write config.json, run apex_deck.js, QA-render, fix any defect, deliver deck.pptx.

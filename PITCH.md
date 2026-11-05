# ProposalDesk: pitch script (target 4:30, limit 5:00)

Fill in the [brackets] with your own details. Everything else is ready to read.

## 0:00 – 0:30 Who you are
"Hi, I'm [name]. I'm a [your role] from [city]. I build [one line about what you build]."

## 0:30 – 1:15 Your best work
"The project I'm proudest of is [project]. [One sentence on what it does]. [One sentence on a result: users, revenue, speed, a problem solved]. [Link or name]."
Pick one project, not three. Say what you personally built.

## 1:15 – 2:00 The problem and why this wins
"Freelancers write the same kind of proposal again and again, and then lose track of which ones are pending. Most AI tools answer that with a new app that has its own AI, its own subscription and its own learning curve.

ProposalDesk has no AI inside. The freelancer already has Claude. They connect it once, and from then on they just say what the job is. Claude writes the scope, the line items and the terms. My app saves it, adds up the total, lets them edit it, tracks Sent, Accepted and Rejected, and gives the client a clean link.

Three reasons this wins: there is nothing new to learn, because they just talk to Claude; I pay nothing for AI, so the margin is high; and the proposals are structured data the freelancer owns and can edit, not a chat that scrolls away."

## 2:00 – 3:45 Live demo (rehearse this twice)
1. **(15 s)** Show the app logged in, empty list. "Nothing here yet."
2. **(40 s)** Switch to Claude. Type: *"Draft a proposal for Acme for a 3-page brand refresh. Design is 3 days at ₹15,000 a day, plus ₹15,000 for handover. Valid for two weeks, 50% advance."* Let Claude call the tool. Point at the tool call.
3. **(15 s)** Back in the app, refresh. The proposal is there, total ₹60,000.
4. **(30 s)** Edit it: change a line item price and the terms, save. "The total updates."
5. **(15 s)** Back in Claude: *"Mark the Acme proposal as Sent."* Show the status change in the app.
6. **(10 s)** Open the client link in a private window. "This is what the client sees. They can print it as a PDF."

Backup plan: record the demo once beforehand and keep it as a fallback clip.

## 3:45 – 4:30 The economics
"Free for the first 3 proposals, then ₹499 a month, about nine dollars, for unlimited.

My costs are hosting and a small payment fee. Roughly ₹800 a month for the server and disk, whatever the number of users, because all AI is paid for by the customer's own Claude subscription. About 2 paying customers cover the server. At 100 paying customers that is about ₹49,900 a month in revenue against roughly ₹3,000 in costs, so around 94% gross margin.

Next steps: payments, email sending, and templates by profession, such as designers, developers and writers."

## 4:30 – 4:45 Close
"The app is live, the link and connect steps are in my submission. Thanks for watching."

---

## Economics table (assumptions, check current prices before you quote them)

| Item | Assumption | Per month |
|---|---|---|
| Revenue per Pro customer | ₹499 | ₹499 |
| Server + 1 GB disk | small paid instance | about ₹800 total, fixed |
| Payment fee | about 2.5% of revenue | about ₹12 per customer |
| AI cost | customer's own Claude | ₹0 |

| Paying customers | Revenue | Costs | Profit |
|---|---|---|---|
| 2 | ₹998 | about ₹825 | about ₹173 |
| 10 | ₹4,990 | about ₹925 | about ₹4,065 |
| 100 | ₹49,900 | about ₹2,050 | about ₹47,850 |

Server costs will rise at larger scale; the table keeps them flat for simplicity. Say "roughly" when you present it.

## Honest risks to be ready for
- **Customers need a Claude plan that supports custom connectors.** Say this in the pitch if asked.
- **Claude could ship proposals natively.** Answer: the value is the tracking, editing and client link, which a chat does not give.
- **Security:** the MCP link is a secret URL. Customers can revoke it with one click. OAuth is the next step.

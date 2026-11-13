# Email: OneDrive + Power Automate (shared with the Safety Health Report)

The new Outlook can't be scripted, Microsoft 365 blocks SMTP AUTH, and Graph `Mail.Send` needs IT.
So, like the Safety Health Report, this report hands its email to a Power Automate flow through
your work OneDrive (`email.method: onedrive`):

```
PC: python -m report ──► OneDrive - Hillwood\HCS Safety Report\Attachments\National_Active_Project_Summary_… .pdf
                     └─► OneDrive - Hillwood\HCS Safety Report\Outbox\message ….json   (to, cc, subject, html, attachment)
                                    │ OneDrive syncs
Cloud: flow "HCS Safety Report email" ── new file in /HCS Safety Report/Outbox ──► waits 2 min ──►
       reads the message ──► gets the attachment ──► Send an email (V2) from your mailbox
```

**There is no new flow to build.** The flow sends whatever message file lands in `Outbox`, using the
recipients, subject, body and attachment named in that file. Both reports write the same format into the
same folder, so the existing flow sends both. Recipients come from `email.to` / `email.cc` in this repo's
`config.yaml`, not from the flow.

If the flow doesn't exist yet on this account, build it once by following
`docs/power-automate-flow.md` in the HCS-Safety-Scorecard repo (about 15 minutes). It needs no changes for
PDFs. To give this report its own folder instead, create a second flow pointing at that folder and set
`email.onedrive.folder` here.

## Test it

```powershell
.\.venv\Scripts\python.exe -m report          # real run: sends to email.to (just you, until changed)
```

The email arrives in 3–5 minutes (OneDrive sync, then the flow's 2-minute wait). To watch it, go to
make.powerautomate.com → **My flows** → *HCS Safety Report email* → **Run history**. For the troubleshooting
table, see the Safety Scorecard's copy of this doc.

To stop emails, set `email.enabled: false` here (affects only this report) or turn the flow off (affects both reports).

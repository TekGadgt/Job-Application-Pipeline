Tier 1: Documented Public API

Lever
- Detection Pattern: jobs.lever.co/{company_slug}
- API Endpoint: api.lever.co/v0/postings/{company_slug}?mode=json

Greenhouse
- Detection Pattern: job-boards.greenhouse.io/{org}
- API Endpoint: https://boards-api.greenhouse.io/v1/boards/{org}/jobs

Tier 2: Internal/Hidden API (returns JSON, no browser rendering)

These don't have documented public APIs, but their careers pages make internal API calls that return structured JSON. We can hit those endpoints directly:

Ashby
- Detection Pattern: jobs.ashbyhq.com/{org}
- API Endpoint: api.ashbyhq.com/posting-api/job-board/{org}

Workday
- Detection Pattern: {subdomain}.{wd_id}.myworkdayjobs.com
- API Endpoint: POST {base}/wday/cxs/{tenant}/{site}/jobs
- Notes: Returns jobPostings array. Paginated (20 per page). This is huge — Workday is ~39% of large employers.

SmartRecruiters
- Detection Pattern: careers.smartrecruiters.com/{slug}
- API Endpoint: GET api.smartrecruiters.com/v1/companies/{slug}/postings
- Notes: Documented public API! Full job details included.

iCIMS
- Detection Pattern: {company}.icims.com
- API Endpoint: GET {company}.icims.com/sitemap.xml
- Notes: Sitemap lists all job URLs with lastmod. Then scrape individual job pages for JSON-LD (JobPosting schema).

Oracle Taleo
- Detection Pattern: {company}.taleo.net
- API Endpoint: POST {base}/careersection/rest/jobboard/searchjobs
- Notes: Needs CSRF token + portal param extracted from page first.

Oracle Cloud HCM
- Detection Pattern: {tenant}.oraclecloud.com/hcmUI/CandidateExperience (1/3)
- API Endpoint: GET {tenant}.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions
- Notes: Uses finder param with siteNumber.

BambooHR
- Detection Pattern: {company}.bamboohr.com/careers
- API Endpoint: GET {company}.bamboohr.com/careers/list
- Notes: Simple JSON array.

Workable
- Detection Pattern: apply.workable.com/{org}
- API Endpoint: POST apply.workable.com/api/v3/accounts/{org}/jobs
- Notes: ⚠️ Aggressive IP banning after ~100 requests. Skip for now.

Jobvite
- Detection Pattern: jobs.jobvite.com/{company}
- API Endpoint: No API — HTML scrape
- Notes: Parse jv-job-list tables.

Eightfold
- Detection Pattern: {company}.eightfold.ai/careers
- API Endpoint: GET {company}.eightfold.ai/api/pcsx/search?domain={id}
- Notes: Need window._EF_GROUP_ID from page first.

Tier 3: HTML Scrape Only (need ScrapingBee/JS rendering)

Teamtailor
- Detection Pattern: {company}.teamtailor.com
- Method: RSS feed at /jobs.rss or parse HTML

BreezyHR
- Detection Pattern: {company}.breezy.hr
- Method: Parse /p/{job_id} links

Recruitee
- Detection Pattern: {company}.recruitee.com
- Method: Parse data-component="PublicApp" JSON

UltiPro
- Detection Pattern: recruiting.ultipro.com/{code}/JobBoard/{id}
- Method: AJAX POST returns HTML
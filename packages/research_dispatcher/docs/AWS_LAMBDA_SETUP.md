# AWS Lambda Document Viewer Setup

The simplest approach is **Lambda + Function URL** - serverless, cheap, and serves HTML properly.

## Step 1: Create the Lambda Function

1. Go to **AWS Console** → **Lambda** → **Create function**
2. Choose:
   - **Author from scratch**
   - Function name: `research-dispatch-document`
   - Runtime: **Node.js 20.x**
   - Architecture: **arm64** (cheaper)
3. Click **Create function**

## Step 2: Enable Public URL

1. In your function, go to **Configuration** → **Function URL**
2. Click **Create function URL**
3. Auth type: **NONE** (public access)
4. Click **Save**
5. Copy the Function URL (looks like `https://xxxxx.lambda-url.us-east-1.on.aws/`)

## Step 3: Add Environment Variables

1. Go to **Configuration** → **Environment variables**
2. Add:
   ```
   SUPABASE_URL = https://qeyhmsqepsenhvtkryjh.supabase.co
   SUPABASE_KEY = your_service_role_key
   ```

## Step 4: Add the Code

In the **Code** tab, replace `index.mjs` with:

```javascript
const SUPABASE_URL = process.env.SUPABASE_URL;
const SUPABASE_KEY = process.env.SUPABASE_KEY;

function escapeHtml(text) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// Convert markdown-style text to HTML (# headings, - bullets)
function formatText(text) {
  const lines = text.split('\n');
  let html = '';
  let inList = false;

  for (const line of lines) {
    const trimmed = line.trim();

    if (trimmed.startsWith('# ')) {
      if (inList) { html += '</ul>'; inList = false; }
      html += `<h3>${escapeHtml(trimmed.slice(2))}</h3>`;
    }
    else if (trimmed.startsWith('- ')) {
      if (!inList) { html += '<ul>'; inList = true; }
      html += `<li>${escapeHtml(trimmed.slice(2))}</li>`;
    }
    else if (trimmed === '') {
      if (inList) { html += '</ul>'; inList = false; }
      html += '<br>';
    }
    else {
      if (inList) { html += '</ul>'; inList = false; }
      html += `<p>${escapeHtml(trimmed)}</p>`;
    }
  }

  if (inList) html += '</ul>';
  return html;
}

export const handler = async (event) => {
  const id = event.queryStringParameters?.id;

  if (!id) {
    return {
      statusCode: 400,
      headers: { 'Content-Type': 'text/html' },
      body: '<html><body><h1>Missing document ID</h1></body></html>'
    };
  }

  try {
    const response = await fetch(
      `${SUPABASE_URL}/rest/v1/parsed_research?id=eq.${id}&select=document_name,source,source_date,parsed_data`,
      {
        headers: {
          'apikey': SUPABASE_KEY,
          'Authorization': `Bearer ${SUPABASE_KEY}`
        }
      }
    );

    const data = await response.json();

    if (!data || data.length === 0) {
      return {
        statusCode: 404,
        headers: { 'Content-Type': 'text/html' },
        body: '<html><body><h1>Document not found</h1></body></html>'
      };
    }

    const doc = data[0];
    const fullText = doc.parsed_data?.full_text || 'No text available.';

    const html = `<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${escapeHtml(doc.document_name || 'Document')} - Research Dispatch</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: Helvetica, Arial, sans-serif; background: #FFFFFF; color: #000000; }
    .header { background: #000000; padding: 20px 40px; }
    .header-inner { max-width: 900px; margin: 0 auto; }
    .header span { color: #FF4458; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; }
    .header h1 { color: #FFFFFF; font-size: 24px; font-weight: bold; margin-top: 4px; }
    .container { max-width: 900px; margin: 0 auto; padding: 40px; }
    .meta-bar { display: flex; justify-content: space-between; padding: 16px 0; border-bottom: 2px solid #FF4458; margin-bottom: 32px; }
    .meta-bar .source { font-size: 14px; font-weight: bold; }
    .meta-bar .date { font-size: 12px; color: #999999; }
    .document-title { color: #FF4458; font-size: 28px; font-weight: bold; margin-bottom: 24px; }
    .content { background: #F8F8F8; border-left: 4px solid #FF4458; padding: 32px; font-size: 14px; line-height: 1.8; }
    .content h3 { color: #FF4458; font-size: 18px; margin: 24px 0 12px 0; }
    .content h3:first-child { margin-top: 0; }
    .content p { margin-bottom: 12px; }
    .content ul { margin: 12px 0 12px 24px; }
    .content li { margin-bottom: 8px; }
    .footer { text-align: center; padding: 40px 20px; color: #999999; font-size: 12px; }
  </style>
</head>
<body>
  <div class="header">
    <div class="header-inner">
      <span>Research Dispatch</span>
      <h1>Full Document</h1>
    </div>
  </div>
  <div class="container">
    <div class="meta-bar">
      <div class="source">${escapeHtml(doc.source || 'Unknown')}</div>
      <div class="date">${escapeHtml(doc.source_date || '')}</div>
    </div>
    <h2 class="document-title">${escapeHtml(doc.document_name || 'Untitled')}</h2>
    <div class="content">${formatText(fullText)}</div>
  </div>
  <div class="footer">Research Dispatch · Document Viewer</div>
</body>
</html>`;

    return {
      statusCode: 200,
      headers: { 'Content-Type': 'text/html' },
      body: html
    };
  } catch (err) {
    console.error(err);
    return {
      statusCode: 500,
      headers: { 'Content-Type': 'text/html' },
      body: '<html><body><h1>Service error</h1></body></html>'
    };
  }
};
```

5. Click **Deploy**

## Step 5: Test It

Visit: `https://your-function-url.lambda-url.us-east-1.on.aws/?id=YOUR_DOCUMENT_UUID`

## Step 6: Update PDF Generator

Once working, add `LAMBDA_DOCUMENT_URL` to your `.env`:

```
LAMBDA_DOCUMENT_URL=https://your-function-url.lambda-url.us-east-1.on.aws/
```

Then update `config.py` and `pdf_generator.py` to use the Lambda URL for the [View Full Text] link.

---

## Cost

Essentially free for your usage:
- Lambda free tier = 1M requests/month
- Function URL = no additional cost

## Troubleshooting

**Function URL not working?**
- Check that Auth type is set to NONE
- Verify environment variables are set correctly

**Document not found?**
- Verify the document UUID exists in your `parsed_research` table
- Check Lambda logs in CloudWatch for errors

**CORS issues?**
- Add CORS headers if needed (shouldn't be required for direct browser access)

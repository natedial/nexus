import { serve } from 'https://deno.land/std@0.168.0/http/server.ts'
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

const htmlHeaders = {
  'Content-Type': 'text/html; charset=utf-8',
  'Access-Control-Allow-Origin': '*',
  'Content-Security-Policy': "default-src 'self'; style-src 'unsafe-inline'; script-src 'none'",
  'X-Content-Type-Options': 'nosniff',
}

// Escape HTML to prevent XSS
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

serve(async (req) => {
  // Handle CORS preflight
  if (req.method === 'OPTIONS') {
    return new Response(null, { headers: htmlHeaders })
  }

  try {
    const url = new URL(req.url)
    const id = url.searchParams.get('id')

    if (!id) {
      return new Response(
        '<html><body><h1>Invalid request</h1><p>Document ID is required.</p></body></html>',
        { status: 400, headers: htmlHeaders }
      )
    }

    const supabase = createClient(
      Deno.env.get('SUPABASE_URL')!,
      Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
    )

    const { data, error } = await supabase
      .from('parsed_research')
      .select('document_name, source, source_date, parsed_data')
      .eq('id', id)
      .single()

    if (error) {
      console.error('Database error:', error)
      return new Response(
        '<html><body><h1>Service temporarily unavailable</h1><p>Unable to retrieve document. Please try again later.</p></body></html>',
        { status: 503, headers: htmlHeaders }
      )
    }

    if (!data) {
      return new Response(
        '<html><body><h1>Document not found</h1><p>The requested document could not be found.</p></body></html>',
        { status: 404, headers: htmlHeaders }
      )
    }

    const fullText = data.parsed_data?.full_text || 'No text available for this document.'

    // Styled HTML page matching format_rules.yaml theme
    const html = `<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${escapeHtml(data.document_name || 'Document')} - Research Dispatch</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: Helvetica, Arial, sans-serif;
      background: #FFFFFF;
      color: #000000;
      min-height: 100vh;
    }
    .header {
      background: #000000;
      padding: 20px 40px;
      position: sticky;
      top: 0;
      z-index: 100;
    }
    .header-inner {
      max-width: 900px;
      margin: 0 auto;
    }
    .header span {
      color: #FF4458;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 1px;
    }
    .header h1 {
      color: #FFFFFF;
      font-size: 24px;
      font-weight: bold;
      margin-top: 4px;
    }
    .container {
      max-width: 900px;
      margin: 0 auto;
      padding: 40px;
    }
    .meta-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 16px 0;
      border-bottom: 2px solid #FF4458;
      margin-bottom: 32px;
    }
    .meta-bar .source {
      font-size: 14px;
      color: #000000;
      font-weight: bold;
    }
    .meta-bar .date {
      font-size: 12px;
      color: #999999;
    }
    .document-title {
      color: #FF4458;
      font-size: 28px;
      font-weight: bold;
      margin-bottom: 24px;
      line-height: 1.3;
    }
    .content {
      background: #F8F8F8;
      border-left: 4px solid #FF4458;
      padding: 32px;
      font-size: 14px;
      line-height: 1.8;
      white-space: pre-wrap;
      word-wrap: break-word;
    }
    .footer {
      text-align: center;
      padding: 40px 20px;
      color: #999999;
      font-size: 12px;
      border-top: 1px solid #F0F0F0;
      margin-top: 40px;
    }
    @media print {
      .header { position: static; }
      .content { background: #FFFFFF; border-left-color: #000000; }
    }
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
      <div class="source">${escapeHtml(data.source || 'Unknown source')}</div>
      <div class="date">${escapeHtml(data.source_date || 'No date')}</div>
    </div>
    <h2 class="document-title">${escapeHtml(data.document_name || 'Untitled Document')}</h2>
    <div class="content">${escapeHtml(fullText)}</div>
  </div>
  <div class="footer">
    Research Dispatch · Document Viewer
  </div>
</body>
</html>`

    return new Response(html, { headers: htmlHeaders })
  } catch (err) {
    console.error('Unexpected error:', err)
    return new Response(
      '<html><body><h1>Service temporarily unavailable</h1><p>Please try again later.</p></body></html>',
      { status: 503, headers: htmlHeaders }
    )
  }
})

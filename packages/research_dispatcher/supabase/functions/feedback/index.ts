import { serve } from 'https://deno.land/std@0.168.0/http/server.ts'
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

const headers = {
  'Content-Type': 'text/plain; charset=utf-8',
  'Access-Control-Allow-Origin': '*',
}

serve(async (req) => {
  if (req.method === 'OPTIONS') {
    return new Response(null, { headers })
  }

  try {
    const url = new URL(req.url)
    const doc_id = url.searchParams.get('doc')
    const item_id = url.searchParams.get('item')
    const action = url.searchParams.get('action')

    if (!doc_id || !item_id || !action) {
      return new Response('Invalid request: missing parameters', { status: 400, headers })
    }

    if (!['useful', 'flag'].includes(action)) {
      return new Response('Invalid action', { status: 400, headers })
    }

    const supabase = createClient(
      Deno.env.get('SUPABASE_URL')!,
      Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
    )

    const { error } = await supabase.from('report_feedback').insert({
      doc_id,
      item_id,
      action
    })

    if (error) {
      console.error('Database error:', error)
      return new Response('Error saving feedback. Please try again.', { status: 500, headers })
    }

    return new Response(
      `Thanks for your feedback! (${action === 'useful' ? 'Marked as useful' : 'Flagged for review'})\n\nYou can close this tab.`,
      { headers }
    )
  } catch (err) {
    console.error('Unexpected error:', err)
    return new Response('Service temporarily unavailable', { status: 503, headers })
  }
})

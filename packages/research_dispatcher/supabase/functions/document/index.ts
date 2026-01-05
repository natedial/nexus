// Setup type definitions for built-in Supabase Runtime APIs
import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

// Escape HTML to prevent XSS
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// Format markdown-style text into clean HTML with inline styles
function formatFullText(text: string): string {
  if (!text || !text.trim()) {
    return '<p style="color:#999;font-style:italic;">No text available for this document.</p>';
  }

  let content = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const lines = content.split("\n");
  const output: string[] = [];
  let inList = false;
  let listType = "";
  let currentParagraph: string[] = [];

  const flushParagraph = () => {
    if (currentParagraph.length > 0) {
      const t = currentParagraph.join(" ").trim();
      if (t) {
        output.push(`<p style="margin-bottom:1.2em;text-align:justify;">${escapeHtml(t)}</p>`);
      }
      currentParagraph = [];
    }
  };

  const closeList = () => {
    if (inList) {
      output.push(`</${listType}>`);
      inList = false;
      listType = "";
    }
  };

  for (const line of lines) {
    const trimmed = line.trim();

    if (!trimmed) {
      flushParagraph();
      closeList();
      continue;
    }

    // Markdown headers
    const headerMatch = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (headerMatch) {
      flushParagraph();
      closeList();
      const level = headerMatch[1].length;
      const styles =
        level === 1
          ? "font-size:24px;font-weight:bold;color:#FF4458;margin:1.5em 0 0.8em 0;"
          : level === 2
          ? "font-size:20px;font-weight:bold;color:#000;margin:1.5em 0 0.6em 0;border-bottom:1px solid #eee;padding-bottom:0.3em;"
          : "font-size:16px;font-weight:bold;color:#333;margin:1.2em 0 0.5em 0;";
      output.push(`<div style="${styles}">${escapeHtml(headerMatch[2])}</div>`);
      continue;
    }

    // Numbered list
    const numberedMatch = trimmed.match(/^(\d+)[.)]\s+(.+)$/);
    if (numberedMatch) {
      flushParagraph();
      if (!inList || listType !== "ol") {
        closeList();
        output.push('<ol style="margin:1em 0 1.5em 1.5em;padding:0;">');
        inList = true;
        listType = "ol";
      }
      output.push(`<li style="margin-bottom:0.5em;">${escapeHtml(numberedMatch[2])}</li>`);
      continue;
    }

    // Bullet list
    const bulletMatch = trimmed.match(/^[-*•]\s+(.+)$/);
    if (bulletMatch) {
      flushParagraph();
      if (!inList || listType !== "ul") {
        closeList();
        output.push('<ul style="margin:1em 0 1.5em 1.5em;padding:0;">');
        inList = true;
        listType = "ul";
      }
      output.push(`<li style="margin-bottom:0.5em;">${escapeHtml(bulletMatch[1])}</li>`);
      continue;
    }

    closeList();
    currentParagraph.push(trimmed);
  }

  flushParagraph();
  closeList();

  let html = output.join("\n");
  html = html
    .replace(/&amp;#x26;/g, "&amp;")
    .replace(/&amp;#(\d+);/g, "&#$1;")
    .replace(/&amp;([a-z]+);/gi, "&$1;");

  return html;
}

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

console.info("document function started");

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { headers: corsHeaders });
  }

  try {
    const url = new URL(req.url);
    const id = url.searchParams.get("id");

    if (!id) {
      return new Response(
        JSON.stringify({ error: "Document ID is required" }),
        { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    const supabase = createClient(
      Deno.env.get("SUPABASE_URL")!,
      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
    );

    const { data, error } = await supabase
      .from("parsed_research")
      .select("document_name, source, source_date, parsed_data")
      .eq("id", id)
      .single();

    if (error) {
      console.error("Database error:", error);
      return new Response(
        JSON.stringify({ error: "Unable to retrieve document" }),
        { status: 503, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    if (!data) {
      return new Response(
        JSON.stringify({ error: "Document not found" }),
        { status: 404, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    const fullText = data.parsed_data?.full_text || "";
    const formattedContent = formatFullText(fullText);

    return new Response(
      JSON.stringify({
        document_name: data.document_name || "Untitled Document",
        source: data.source || "Unknown source",
        source_date: data.source_date || "",
        content_html: formattedContent,
      }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  } catch (err) {
    console.error("Unexpected error:", err);
    return new Response(
      JSON.stringify({ error: "Service temporarily unavailable" }),
      { status: 503, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  }
});

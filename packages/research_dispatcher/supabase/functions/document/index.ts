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

const textEncoder = new TextEncoder();
const textDecoder = new TextDecoder();

function decodeBase64Url(input: string): Uint8Array {
  const normalized = input.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

function timingSafeEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) {
    return false;
  }
  let result = 0;
  for (let i = 0; i < a.length; i += 1) {
    result |= a[i] ^ b[i];
  }
  return result === 0;
}

async function verifySignedToken(
  token: string,
  expectedId: string,
  secret: string,
): Promise<boolean> {
  const parts = token.split(".");
  if (parts.length !== 2) {
    return false;
  }
  const [payloadB64, signatureB64] = parts;
  if (!payloadB64 || !signatureB64) {
    return false;
  }

  let payload;
  try {
    const payloadBytes = decodeBase64Url(payloadB64);
    payload = JSON.parse(textDecoder.decode(payloadBytes));
  } catch (_err) {
    return false;
  }

  if (!payload?.id || payload.id !== expectedId) {
    return false;
  }
  if (!payload.exp || typeof payload.exp !== "number") {
    return false;
  }
  if (payload.exp < Math.floor(Date.now() / 1000)) {
    return false;
  }

  const key = await crypto.subtle.importKey(
    "raw",
    textEncoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const expectedSig = new Uint8Array(
    await crypto.subtle.sign("HMAC", key, textEncoder.encode(payloadB64)),
  );
  const providedSig = decodeBase64Url(signatureB64);
  return timingSafeEqual(expectedSig, providedSig);
}

const allowedOrigins = (Deno.env.get("ALLOWED_ORIGINS") ?? "")
  .split(",")
  .map((origin) => origin.trim())
  .filter(Boolean);

const isOriginAllowed = (origin: string | null): boolean => {
  if (!origin) {
    return true;
  }
  return allowedOrigins.includes(origin);
};

const buildCorsHeaders = (req: Request): HeadersInit => {
  const origin = req.headers.get("origin");
  const allowOrigin = origin && allowedOrigins.includes(origin) ? origin : origin ? "null" : "*";
  return {
    "Access-Control-Allow-Origin": allowOrigin,
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Vary": "Origin",
  };
};

console.info("document function started");

Deno.serve(async (req: Request) => {
  const corsHeaders = buildCorsHeaders(req);
  if (req.method === "OPTIONS") {
    return new Response(null, { headers: corsHeaders });
  }

  try {
    if (!isOriginAllowed(req.headers.get("origin"))) {
      return new Response(
        JSON.stringify({ error: "Origin not allowed" }),
        { status: 403, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    const url = new URL(req.url);
    const id = url.searchParams.get("id");

    if (!id) {
      return new Response(
        JSON.stringify({ error: "Document ID is required" }),
        { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    const authHeader = req.headers.get("authorization");
    const token = url.searchParams.get("token");
    const supabaseUrl = Deno.env.get("SUPABASE_URL");
    const supabaseAnonKey = Deno.env.get("SUPABASE_ANON_KEY");
    const supabaseServiceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
    const linkSecret = Deno.env.get("DOCUMENT_LINK_SECRET");

    if (!supabaseUrl || !supabaseAnonKey) {
      console.error("Missing Supabase configuration");
      return new Response(
        JSON.stringify({ error: "Service configuration error" }),
        { status: 503, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    let supabase;
    if (token && linkSecret) {
      const valid = await verifySignedToken(token, id, linkSecret);
      if (valid) {
        if (!supabaseServiceKey) {
          console.error("Missing service role key for signed links");
          return new Response(
            JSON.stringify({ error: "Service configuration error" }),
            { status: 503, headers: { ...corsHeaders, "Content-Type": "application/json" } }
          );
        }
        supabase = createClient(supabaseUrl, supabaseServiceKey);
      }
    }

    if (!supabase) {
      if (!authHeader) {
        return new Response(
          JSON.stringify({ error: "Authorization required" }),
          { status: 401, headers: { ...corsHeaders, "Content-Type": "application/json" } }
        );
      }

      supabase = createClient(supabaseUrl, supabaseAnonKey, {
        global: {
          headers: { Authorization: authHeader },
        },
      });

      const { data: authData, error: authError } = await supabase.auth.getUser();
      if (authError || !authData?.user) {
        return new Response(
          JSON.stringify({ error: "Unauthorized" }),
          { status: 401, headers: { ...corsHeaders, "Content-Type": "application/json" } }
        );
      }
    }

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

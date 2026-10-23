<script lang="ts">
	// Evidence per flag type (file 08 §4.2 EvidencePane; S1 typed evidence in backend/dispatcher/contract.py).
	import type { Evidence, Suggestion } from '$lib/api_endpoint';
	import { Button } from '$lib/components/ui/button';
	import AssetImage from './AssetImage.svelte';
	import GenericEvidence from './GenericEvidence.svelte';
	import LowConfidencePane from './LowConfidencePane.svelte';
	import { around, fmtBytes } from './evidence';
	import SparklesIcon from '@lucide/svelte/icons/sparkles';

	interface Props {
		evidence: Evidence | null;
		suggestion: Suggestion | null;
		/** Called when the reviewer picks a candidate unit (UNIT_AMBIGUITY telemetry). */
		onPickUnit?: (unit: string, gaugeOrAbs: string) => void;
	}

	let { evidence, suggestion, onPickUnit }: Props = $props();
	const n = (v: number | null | undefined) => (v === null || v === undefined ? '—' : Number(v.toPrecision(5)).toString());
	const STAT_KEYS = ['min', 'max', 'mean', 'p50', 'p99', 'std'] as const;
</script>

<section class="grid content-start gap-3 text-sm" aria-label="Evidence">
	{#if !evidence}
		<p class="text-muted-foreground m-0">No evidence attached to this flag.</p>
	{:else if evidence.kind === 'unit_telemetry'}
		<h4 class="m-0 text-[13px]">
			Channel <code class="bg-muted rounded px-1">{evidence.channel}</code>{evidence.raw_unit ? ` · raw unit “${evidence.raw_unit}”` : ''}{evidence.quantity_guess
				? ` · looks like ${evidence.quantity_guess}`
				: ''}
		</h4>
		{#if evidence.note}<p class="bg-warn-bg border-warn-border m-0 rounded-md border px-3 py-1.5 text-[13px]" role="note">{evidence.note}</p>{/if}
		{#if evidence.header_lines.length}
			<pre class="code-block m-0 max-h-40" aria-label="File header">{#each evidence.header_lines as line, i (i)}<span
						class={line.includes(evidence.channel) ? 'hit bg-warn-bg text-warn -mx-1 rounded-sm px-1 font-semibold' : ''}>{line}
</span>{/each}</pre>
		{/if}
		<div class="overflow-x-auto rounded-md border">
			<table class="num w-full text-xs">
				<tbody
					><tr class="bg-muted/60">{#each STAT_KEYS as k (k)}<th class="text-muted-foreground px-2.5 py-1 text-right font-medium">{k}</th>{/each}</tr>
					<tr>{#each STAT_KEYS as k (k)}<td class="border-t px-2.5 py-1 text-right font-mono">{n(evidence.stats[k])}</td>{/each}</tr></tbody
				>
			</table>
		</div>
		{#if evidence.sparkline_uri}<AssetImage
				uri={evidence.sparkline_uri}
				alt="Sparkline of {evidence.channel}"
				class="h-12 w-full max-w-[22rem] rounded-sm border object-fill"
			/>{/if}
		{#if evidence.sanity}
			<p class="text-muted-foreground m-0">
				Sanity bounds for {evidence.sanity.quantity}: {n(evidence.sanity.min)} … {n(evidence.sanity.max)} {evidence.sanity.unit}
			</p>
		{/if}
		{#if evidence.candidate_units.length}
			<div class="grid gap-1.5">
				<h4 class="eyebrow">Candidate units</h4>
				<ul class="m-0 grid list-none gap-1 p-0">
					{#each evidence.candidate_units as c (c.unit + c.gauge_or_abs)}
						<li class="flex items-center gap-2">
							<Button variant="outline" size="xs" disabled={!onPickUnit} onclick={() => onPickUnit?.(c.unit, c.gauge_or_abs)}
								>{c.unit} ({c.gauge_or_abs})</Button
							>
							<span class="num font-mono text-xs font-semibold">{c.score.toFixed(2)}</span>
							<span class="text-muted-foreground min-w-0 truncate text-xs" title={c.reason}>{c.reason}</span>
						</li>
					{/each}
				</ul>
			</div>
		{/if}
		{#if evidence.sibling_units.length}
			<div class="grid gap-1.5">
				<h4 class="eyebrow">Units in sibling files</h4>
				<ul class="m-0 grid list-none gap-0.5 p-0 text-[13px]">
					{#each evidence.sibling_units as s, i (i)}<li>
							{s.file_name} · {s.channel}: <strong class="font-medium">{s.unit}</strong> <span class="text-muted-foreground">({s.source})</span>
						</li>{/each}
				</ul>
			</div>
		{/if}
	{:else if evidence.kind === 'array_schema'}
		<h4 class="m-0 text-[13px]">Array shape <span class="font-mono">({evidence.shape.join(', ')}){evidence.dtype ? ` ${evidence.dtype}` : ''}</span></h4>
		<div class="overflow-x-auto rounded-md border">
			<table class="num w-full text-xs">
				<thead
					><tr class="bg-muted/60"
						><th class="text-muted-foreground px-2.5 py-1 text-left font-medium">col</th>{#each STAT_KEYS as k (k)}<th
								class="text-muted-foreground px-2.5 py-1 text-right font-medium">{k}</th
							>{/each}<th><span class="sr-only">Sparkline</span></th></tr
					></thead
				>
				<tbody>
					{#each evidence.columns as c (c.index)}
						<tr class="border-t">
							<td class="px-2.5 py-1 font-mono">col{c.index}</td>
							{#each STAT_KEYS as k (k)}<td class="px-2.5 py-1 text-right font-mono">{n(c[k])}</td>{/each}
							<td class="px-2.5 py-1"
								>{#if c.sparkline_uri}<AssetImage uri={c.sparkline_uri} alt="Sparkline of column {c.index}" class="h-6 w-24 object-fill" />{/if}</td
							>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
		{#if evidence.first_rows.length}
			<details class="rounded-md border">
				<summary class="text-muted-foreground hover:text-foreground px-2.5 py-1.5 text-xs font-medium">First {evidence.first_rows.length} rows</summary>
				<div class="overflow-x-auto border-t">
					<table class="num w-full font-mono text-xs">
						<tbody
							>{#each evidence.first_rows as row, r (r)}<tr class="border-t first:border-t-0"
									>{#each row as v, c (c)}<td class="px-2.5 py-0.5 text-right whitespace-nowrap">{v ?? ''}</td>{/each}</tr
								>{/each}</tbody
						>
					</table>
				</div>
			</details>
		{/if}
		{#if evidence.siblings.length}<p class="m-0">Folder siblings: {evidence.siblings.join(', ')}</p>{/if}
		{#if evidence.pickle_classes.length}<p class="m-0">Pickle classes (never executed): <span class="font-mono text-xs">{evidence.pickle_classes.join(', ')}</span></p>{/if}
		{#if evidence.recommendation}<p class="m-0">{evidence.recommendation}</p>{/if}
	{:else if evidence.kind === 'unit_fact'}
		{@const marked = around(evidence.context, evidence.value_raw)}
		<p class="m-0 font-mono text-base font-semibold">{evidence.value_raw}</p>
		{#if evidence.context}
			<p class="bg-muted/50 m-0 rounded-md px-3 py-2">
				{#if marked}{marked.before}<mark class="bg-warn-bg text-warn rounded px-0.5">{marked.match}</mark>{marked.after}{:else}{evidence.context}{/if}
			</p>
		{/if}
		{#if evidence.candidate_units.length}
			<h4 class="m-0 text-[13px]">Candidate units</h4>
			<ul class="m-0 grid list-none gap-1 p-0">
				{#each evidence.candidate_units as c (c.unit + c.gauge_or_abs)}
					<li class="flex items-center gap-2">
						<button type="button" class="field cursor-pointer px-2 py-0.5" disabled={!onPickUnit} onclick={() => onPickUnit?.(c.unit, c.gauge_or_abs)}
							>{c.unit} ({c.gauge_or_abs})</button
						>
						<span class="num font-mono text-xs">{c.score.toFixed(2)}</span>
						<span class="text-muted-foreground text-xs">{c.reason}</span>
					</li>
				{/each}
			</ul>
		{/if}
	{:else if evidence.kind === 'json_schema'}
		<dl class="kv">
			<dt>Top-level keys</dt>
			<dd class="font-mono text-xs">{evidence.top_level_keys.join(', ') || '—'}</dd>
			<dt>Closest known schema</dt>
			<dd>{evidence.closest_schema ?? 'none'}</dd>
			{#if evidence.missing_keys.length}<dt>Missing for that schema</dt>
				<dd class="text-hard font-mono text-xs">{evidence.missing_keys.join(', ')}</dd>{/if}
		</dl>
		{#if evidence.flattened_sample.length}
			<pre class="code-block max-h-56 overflow-auto text-xs">{evidence.flattened_sample.join('\n')}</pre>
		{/if}
	{:else if evidence.kind === 'low_confidence'}
		<LowConfidencePane {evidence} />
	{:else if evidence.kind === 'file_facts'}
		<dl class="kv">
			<dt>Size</dt>
			<dd class="num font-mono">{fmtBytes(evidence.size_bytes)}</dd>
			<dt>Extension</dt>
			<dd class="font-mono">{evidence.extension ?? '—'}</dd>
			<dt>Folder</dt>
			<dd>{evidence.folder ?? '—'}</dd>
		</dl>
		{#if evidence.note}<p class="m-0">{evidence.note}</p>{/if}
	{:else if evidence.kind === 'sensitive'}
		<p class="m-0">Matched pattern <code>{evidence.pattern}</code>{evidence.line ? ` on line ${evidence.line}` : ''}{evidence.page ? ` on page ${evidence.page}` : ''}. The secret itself is never stored or shown.</p>
		<pre class="code-block overflow-x-auto text-xs">{evidence.redacted_preview}</pre>
	{:else if evidence.kind === 'conflict'}
		<h4 class="m-0 text-[13px]">{evidence.subject}</h4>
		<div class="grid grid-cols-2 gap-2">
			{#each [['A', evidence.a], ['B', evidence.b]] as const as [name, side] (name)}
				<div class="grid content-start gap-1 rounded-md border p-3">
					<strong class="text-muted-foreground text-xs font-medium">Source {name}: {side.label}</strong>
					<p class="m-0 font-mono text-base font-semibold">{side.value}</p>
					<p class="text-muted-foreground m-0 text-xs">{side.provenance}{side.date ? ` · ${side.date}` : ''}</p>
					{#if side.doc_id}<a href="/docs/{side.doc_id}/viewer" class="text-xs">Open document</a>{/if}
				</div>
			{/each}
		</div>
	{:else if evidence.kind === 'parse_failure'}
		<p class="text-hard m-0 font-medium">{evidence.error}</p>
		<dl class="kv">
			<dt>Magic bytes</dt>
			<dd><code>{evidence.magic_bytes_hex}</code></dd>
			{#if evidence.detected_mime}<dt>Detected type</dt>
				<dd>{evidence.detected_mime}</dd>{/if}
			{#if evidence.extension}<dt>Extension</dt>
				<dd>{evidence.extension}</dd>{/if}
			{#if evidence.size_bytes !== null && evidence.size_bytes !== undefined}<dt>Size</dt>
				<dd class="num">{evidence.size_bytes.toLocaleString()} bytes</dd>{/if}
		</dl>
		{#if evidence.first_kb_preview}
			<details>
				<summary class="text-muted-foreground hover:text-foreground text-xs font-medium">First KB</summary>
				<pre class="code-block mt-1.5 mb-0 max-h-64">{evidence.first_kb_preview}</pre>
			</details>
		{/if}
		{#if evidence.partial_output}
			<details>
				<summary class="text-muted-foreground hover:text-foreground text-xs font-medium">Partial output</summary>
				<pre class="code-block mt-1.5 mb-0 max-h-64">{evidence.partial_output}</pre>
			</details>
		{/if}
	{:else}
		<GenericEvidence evidence={evidence as unknown as Record<string, unknown>} />
	{/if}

	{#if suggestion}
		<div class="bg-info-bg border-info-border grid gap-1 rounded-md border px-3 py-2">
			<h4 class="text-info m-0 flex items-center gap-1.5 text-xs font-medium">
				<SparklesIcon class="size-3.5" aria-hidden="true" /> Suggested ({suggestion.proposed_by}, confidence {suggestion.confidence.toFixed(2)})
			</h4>
			<p class="m-0 text-[13px]">{suggestion.rationale}</p>
		</div>
	{/if}
</section>

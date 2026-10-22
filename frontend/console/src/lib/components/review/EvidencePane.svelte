<script lang="ts">
	// Evidence per flag type (file 08 §4.2 EvidencePane; S1 typed evidence in backend/dispatcher/contract.py).
	import type { Evidence, Suggestion } from '$lib/api_endpoint';
	import AssetImage from './AssetImage.svelte';
	import GenericEvidence from './GenericEvidence.svelte';

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

<section class="evidence" aria-label="Evidence">
	{#if !evidence}
		<p class="muted">No evidence attached to this flag.</p>
	{:else if evidence.kind === 'unit_telemetry'}
		<h4>Channel {evidence.channel}{evidence.raw_unit ? ` · raw unit “${evidence.raw_unit}”` : ''}{evidence.quantity_guess ? ` · looks like ${evidence.quantity_guess}` : ''}</h4>
		{#if evidence.note}<p class="note" role="note">{evidence.note}</p>{/if}
		{#if evidence.header_lines.length}
			<pre class="header">{#each evidence.header_lines as line, i (i)}<span class:hit={line.includes(evidence.channel)}>{line}
</span>{/each}</pre>
		{/if}
		<table class="stats">
			<tbody
				><tr>{#each STAT_KEYS as k (k)}<th>{k}</th>{/each}</tr>
				<tr>{#each STAT_KEYS as k (k)}<td>{n(evidence.stats[k])}</td>{/each}</tr></tbody
			>
		</table>
		{#if evidence.sparkline_uri}<AssetImage uri={evidence.sparkline_uri} alt="Sparkline of {evidence.channel}" class="sparkline" />{/if}
		{#if evidence.sanity}
			<p>Sanity bounds for {evidence.sanity.quantity}: {n(evidence.sanity.min)} … {n(evidence.sanity.max)} {evidence.sanity.unit}</p>
		{/if}
		{#if evidence.candidate_units.length}
			<h4>Candidate units</h4>
			<ul class="candidates">
				{#each evidence.candidate_units as c (c.unit + c.gauge_or_abs)}
					<li>
						<button type="button" disabled={!onPickUnit} onclick={() => onPickUnit?.(c.unit, c.gauge_or_abs)}
							>{c.unit} ({c.gauge_or_abs})</button
						>
						<span class="score">{c.score.toFixed(2)}</span> <span class="muted">{c.reason}</span>
					</li>
				{/each}
			</ul>
		{/if}
		{#if evidence.sibling_units.length}
			<h4>Units in sibling files</h4>
			<ul>{#each evidence.sibling_units as s, i (i)}<li>{s.file_name} · {s.channel}: {s.unit} <span class="muted">({s.source})</span></li>{/each}</ul>
		{/if}
	{:else if evidence.kind === 'array_schema'}
		<h4>Array shape ({evidence.shape.join(', ')}){evidence.dtype ? ` ${evidence.dtype}` : ''}</h4>
		<div class="scroll">
			<table class="stats">
				<thead><tr><th>col</th>{#each STAT_KEYS as k (k)}<th>{k}</th>{/each}<th></th></tr></thead>
				<tbody>
					{#each evidence.columns as c (c.index)}
						<tr>
							<td>col{c.index}</td>
							{#each STAT_KEYS as k (k)}<td>{n(c[k])}</td>{/each}
							<td>{#if c.sparkline_uri}<AssetImage uri={c.sparkline_uri} alt="Sparkline of column {c.index}" class="sparkline small" />{/if}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
		{#if evidence.first_rows.length}
			<details>
				<summary>First {evidence.first_rows.length} rows</summary>
				<div class="scroll">
					<table class="stats">
						<tbody>{#each evidence.first_rows as row, r (r)}<tr>{#each row as v, c (c)}<td>{v ?? ''}</td>{/each}</tr>{/each}</tbody>
					</table>
				</div>
			</details>
		{/if}
		{#if evidence.siblings.length}<p>Folder siblings: {evidence.siblings.join(', ')}</p>{/if}
		{#if evidence.pickle_classes.length}<p>Pickle classes (never executed): {evidence.pickle_classes.join(', ')}</p>{/if}
		{#if evidence.recommendation}<p>{evidence.recommendation}</p>{/if}
	{:else if evidence.kind === 'conflict'}
		<h4>{evidence.subject}</h4>
		<div class="sides">
			{#each [['A', evidence.a], ['B', evidence.b]] as const as [name, side] (name)}
				<div class="side">
					<strong>Source {name}: {side.label}</strong>
					<p class="value">{side.value}</p>
					<p class="muted">{side.provenance}{side.date ? ` · ${side.date}` : ''}</p>
					{#if side.doc_id}<a href="/docs/{side.doc_id}/viewer">Open document</a>{/if}
				</div>
			{/each}
		</div>
	{:else if evidence.kind === 'parse_failure'}
		<p class="error">{evidence.error}</p>
		<dl>
			<dt>Magic bytes</dt>
			<dd><code>{evidence.magic_bytes_hex}</code></dd>
			{#if evidence.detected_mime}<dt>Detected type</dt>
				<dd>{evidence.detected_mime}</dd>{/if}
			{#if evidence.extension}<dt>Extension</dt>
				<dd>{evidence.extension}</dd>{/if}
			{#if evidence.size_bytes !== null && evidence.size_bytes !== undefined}<dt>Size</dt>
				<dd>{evidence.size_bytes.toLocaleString()} bytes</dd>{/if}
		</dl>
		{#if evidence.first_kb_preview}
			<details>
				<summary>First KB</summary>
				<pre>{evidence.first_kb_preview}</pre>
			</details>
		{/if}
		{#if evidence.partial_output}
			<details>
				<summary>Partial output</summary>
				<pre>{evidence.partial_output}</pre>
			</details>
		{/if}
	{:else}
		<GenericEvidence evidence={evidence as unknown as Record<string, unknown>} />
	{/if}

	{#if suggestion}
		<div class="suggestion">
			<h4>Suggested ({suggestion.proposed_by}, confidence {suggestion.confidence.toFixed(2)})</h4>
			<p>{suggestion.rationale}</p>
		</div>
	{/if}
</section>

<style>
	.note {
		border-left: 3px solid var(--warn);
		padding: 0.2rem 0.6rem;
		margin: 0.3rem 0;
	}
	.evidence {
		display: grid;
		gap: 0.45rem;
		font-size: 0.82rem;
		align-content: start;
	}
	h4 {
		margin: 0.2rem 0 0;
		font-size: 0.8rem;
	}
	p,
	ul,
	dl {
		margin: 0;
	}
	ul {
		padding-left: 1rem;
	}
	pre {
		margin: 0;
		white-space: pre-wrap;
		font-size: 0.76rem;
	}
	.header {
		background: var(--bg);
		border: 1px solid var(--border);
		padding: 0.4rem;
		max-height: 10rem;
		overflow: auto;
	}
	.hit {
		background: rgb(245 158 11 / 0.25);
	}
	.scroll {
		overflow-x: auto;
	}
	.stats {
		border-collapse: collapse;
	}
	.stats th,
	.stats td {
		border: 1px solid var(--border);
		padding: 0.1rem 0.35rem;
		text-align: right;
		white-space: nowrap;
	}
	:global(img.sparkline) {
		width: 100%;
		max-width: 22rem;
		height: 3rem;
		object-fit: fill;
	}
	:global(img.sparkline.small) {
		width: 6rem;
		height: 1.4rem;
	}
	.candidates {
		list-style: none;
		padding: 0;
		display: grid;
		gap: 0.2rem;
	}
	.candidates button {
		font: inherit;
		font-size: 0.8rem;
		padding: 0.1rem 0.5rem;
		cursor: pointer;
	}
	.score {
		font-weight: 600;
	}
	.sides {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 0.5rem;
	}
	.side {
		border: 1px solid var(--border);
		border-radius: 0.3rem;
		padding: 0.4rem;
	}
	.value {
		font-size: 1rem;
		font-weight: 600;
	}
	dl {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 0.15rem 0.6rem;
	}
	dt {
		opacity: 0.7;
	}
	dd {
		margin: 0;
	}
	.error {
		color: var(--hard);
	}
	.suggestion {
		border-left: 3px solid var(--warn);
		padding-left: 0.5rem;
	}
	.muted {
		opacity: 0.7;
	}
</style>

<script lang="ts">
	import {
		ApiError,
		createRule,
		deactivateRule,
		listRules,
		simulateRule,
		type RuleDraft,
		type RuleSimulation,
		type RuleView
	} from '$lib/api_endpoint';
	import { hasRole } from '$lib/auth/roles';
	import { session } from '$lib/auth/session.svelte';
	import RuleForm from '$lib/components/review/RuleForm.svelte';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';

	let rules = $state<RuleView[]>([]);
	let error = $state('');
	let notice = $state('');
	let busy = $state(false);
	let showInactive = $state(false);
	let simulations = $state<Record<string, RuleSimulation>>({});
	let reload = $state(0);
	let isAdmin = $derived(hasRole(session.user?.roles ?? [], 'admin'));
	let shown = $derived(rules.filter((r) => showInactive || r.active));

	const describe = (e: unknown) =>
		e instanceof ApiError ? (e.status === 501 ? 'The review backend is not connected yet.' : e.detail) : String(e);

	$effect(() => {
		void reload;
		listRules()
			.then((list) => {
				rules = list.items;
				error = '';
			})
			.catch((e) => (error = describe(e)));
	});

	async function act(action: () => Promise<string>) {
		busy = true;
		notice = '';
		error = '';
		try {
			notice = await action();
			reload += 1;
		} catch (e) {
			error = describe(e);
		} finally {
			busy = false;
		}
	}

	const create = (draft: RuleDraft) => act(async () => `Rule ${(await createRule(draft)).rule_id} created.`);
	const deactivate = (rule: RuleView) => act(async () => (await deactivateRule(rule.rule_id), 'Rule deactivated.'));
	async function simulate(rule: RuleView) {
		try {
			simulations[rule.rule_id] = await simulateRule(rule.rule_id);
		} catch (e) {
			error = describe(e);
		}
	}
	const scopeText = (r: RuleView) =>
		[r.scope.scope_root, r.scope.scope_folder_id && `folder ${r.scope.scope_folder_id}`, r.scope.scope_filename_glob, r.scope.scope_extension]
			.filter(Boolean)
			.join(' · ') || 'everywhere';
</script>

<RoleGate roles={session.user?.roles ?? []} role="reviewer">
	<div class="rules">
		<section>
			<div class="head">
				<h1>Rules</h1>
				<a href="/review">← Queue</a>
				<label><input type="checkbox" bind:checked={showInactive} /> show inactive</label>
			</div>
			{#if error}<p role="alert" class="error">{error}</p>{/if}
			{#if notice}<p role="status">{notice}</p>{/if}
			{#if shown.length === 0 && !error}<p class="muted">No rules yet.</p>{/if}
			<ul class="list">
				{#each shown as rule (rule.rule_id)}
					<li class:inactive={!rule.active}>
						<div class="line">
							<strong>{rule.rule_type}</strong>
							<span class="muted">{rule.origin}</span>
							<span>{scopeText(rule)}</span>
							<span class="muted">precedence {rule.precedence}</span>
						</div>
						<div class="line muted">
							{rule.flags_resolved} flags resolved · {rule.runs_mapped} runs mapped · {rule.created_by}, {rule.created_at.slice(0, 10)}
							{#if rule.supersedes_rule_id}· supersedes {rule.supersedes_rule_id.slice(0, 8)}{/if}
						</div>
						<details>
							<summary>Body</summary>
							<pre>{JSON.stringify(rule.body, null, 2)}</pre>
						</details>
						<div class="line">
							<button type="button" onclick={() => simulate(rule)}>Simulate</button>
							{#if isAdmin && rule.active}<button type="button" disabled={busy} onclick={() => deactivate(rule)}>Deactivate</button>{/if}
						</div>
						{#if simulations[rule.rule_id]}
							{@const sim = simulations[rule.rule_id]}
							<p class="sim">
								Matches {sim.matched_documents} documents: {sim.would_resume} would resume, {sim.would_reprocess} would be re-processed.
							</p>
							{#if sim.sample.length}
								<ul class="sample">{#each sim.sample as d (d.doc_id)}<li>{d.path ?? d.title} <span class="muted">{d.status}</span></li>{/each}</ul>
							{/if}
						{/if}
					</li>
				{/each}
			</ul>
		</section>
		<aside>
			<h2>New operator rule</h2>
			<p class="muted">Operator rules are immutable; a change creates a new rule that supersedes the old one.</p>
			<RuleForm {busy} onSubmit={create} />
		</aside>
	</div>
</RoleGate>

<style>
	.rules {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 22rem;
		gap: 1.5rem;
		align-items: start;
	}
	@media (max-width: 900px) {
		.rules {
			grid-template-columns: 1fr;
		}
	}
	.head {
		display: flex;
		gap: 1rem;
		align-items: baseline;
		font-size: 0.85rem;
	}
	h1 {
		font-size: 1.1rem;
		margin: 0;
	}
	h2 {
		font-size: 1rem;
		margin: 0;
	}
	.list {
		list-style: none;
		padding: 0;
		display: grid;
		gap: 0.5rem;
	}
	.list > li {
		border: 1px solid var(--border);
		border-radius: 0.4rem;
		background: var(--surface);
		padding: 0.6rem;
		display: grid;
		gap: 0.3rem;
		font-size: 0.82rem;
	}
	.inactive {
		opacity: 0.6;
	}
	.line {
		display: flex;
		flex-wrap: wrap;
		gap: 0.6rem;
		align-items: baseline;
	}
	pre {
		margin: 0.3rem 0 0;
		font-size: 0.76rem;
	}
	.sim {
		margin: 0;
		font-weight: 600;
	}
	.sample {
		margin: 0;
		padding-left: 1rem;
	}
	.muted {
		opacity: 0.7;
	}
	.error {
		color: var(--hard);
	}
	button {
		font: inherit;
		font-size: 0.8rem;
		padding: 0.2rem 0.6rem;
		cursor: pointer;
	}
</style>

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
	import ArrowLeftIcon from '@lucide/svelte/icons/arrow-left';
	import { Button } from '$lib/components/ui/button';
	import EmptyState from '$lib/components/shell/EmptyState.svelte';
	import Notice from '$lib/components/shell/Notice.svelte';
	import Page from '$lib/components/shell/Page.svelte';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';
	import ToneBadge from '$lib/components/shell/ToneBadge.svelte';

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
	<Page title="Rules" description="Operator and learned rules that resolve flags automatically. The most specific scope wins." width="full">
		{#snippet actions()}
			<label class="text-muted-foreground flex items-center gap-2 text-[13px]"><input type="checkbox" bind:checked={showInactive} /> show inactive</label>
			<Button variant="outline" size="sm" href="/review"><ArrowLeftIcon />Queue</Button>
		{/snippet}
		{#snippet details()}
			<section class="panel" aria-labelledby="new-rule-title">
				<div class="panel-header"><h2 id="new-rule-title" class="panel-title">New operator rule</h2></div>
				<div class="panel-body grid gap-4">
					<p class="text-muted-foreground m-0 text-xs">Operator rules are immutable; a change creates a new rule that supersedes the old one.</p>
					<RuleForm {busy} onSubmit={create} />
				</div>
			</section>
		{/snippet}

		<div class="grid gap-3">
			{#if error}<Notice tone="error">{error}</Notice>{/if}
			{#if notice}<Notice tone="success">{notice}</Notice>{/if}
			{#if shown.length === 0 && !error}
				<EmptyState title="No rules yet." description="Rules appear here when a reviewer applies a resolution to a folder, or creates one on the right." />
			{:else if shown.length}
				<div class="panel">
					<table class="data-table">
						<thead>
							<tr>
								<th scope="col">Rule</th>
								<th scope="col">Scope</th>
								<th scope="col" class="num">Precedence</th>
								<th scope="col">Usage</th>
								<th scope="col">Created</th>
								<th scope="col"><span class="sr-only">Actions</span></th>
							</tr>
						</thead>
						<tbody>
							{#each shown as rule (rule.rule_id)}
								<tr class={rule.active ? '' : 'text-muted-foreground'}>
									<td>
										<div class="flex flex-wrap items-center gap-1.5">
											<strong class="font-mono text-[13px] font-medium">{rule.rule_type}</strong>
											<ToneBadge>{rule.origin}</ToneBadge>
											{#if !rule.active}<ToneBadge tone="outline">inactive</ToneBadge>{/if}
										</div>
										<details class="mt-1">
											<summary class="text-muted-foreground hover:text-foreground text-xs">Body</summary>
											<pre class="code-block mt-1.5 mb-0 max-w-[48ch]">{JSON.stringify(rule.body, null, 2)}</pre>
										</details>
									</td>
									<td class="max-w-[22rem] break-words">{scopeText(rule)}</td>
									<td class="num font-mono">{rule.precedence}</td>
									<td class="text-muted-foreground num text-xs whitespace-nowrap">
										{rule.flags_resolved} flags resolved<br />{rule.runs_mapped} runs mapped
									</td>
									<td class="text-muted-foreground text-xs">
										{rule.created_by}, <span class="font-mono">{rule.created_at.slice(0, 10)}</span>
										{#if rule.supersedes_rule_id}<br />supersedes <span class="font-mono">{rule.supersedes_rule_id.slice(0, 8)}</span>{/if}
									</td>
									<td>
										<div class="flex justify-end gap-1.5">
											<Button variant="outline" size="xs" onclick={() => simulate(rule)}>Simulate</Button>
											{#if isAdmin && rule.active}<Button variant="destructive" size="xs" disabled={busy} onclick={() => deactivate(rule)}>Deactivate</Button>{/if}
										</div>
									</td>
								</tr>
								{#if simulations[rule.rule_id]}
									{@const sim = simulations[rule.rule_id]}
									<tr class="hover:bg-transparent">
										<td colspan="6" class="bg-muted/40">
											<p class="m-0 text-[13px] font-medium">
												Matches {sim.matched_documents} documents: {sim.would_resume} would resume, {sim.would_reprocess} would be re-processed.
											</p>
											{#if sim.sample.length}
												<ul class="m-0 mt-1 grid list-none gap-0.5 p-0 text-xs">
													{#each sim.sample as d (d.doc_id)}<li><span class="font-mono">{d.path ?? d.title}</span> <span class="text-muted-foreground">{d.status}</span></li>{/each}
												</ul>
											{/if}
										</td>
									</tr>
								{/if}
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</div>
	</Page>
</RoleGate>

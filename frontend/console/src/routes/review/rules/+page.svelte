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
	import RuleWizard from '$lib/components/review/RuleWizard.svelte';
	import { deactivatedLine, deactivateLabel, deactivateTitle, savedLine, simulationLine, usageLine } from '$lib/components/review/rule_effect';
	import { RULE_TYPE_HELP } from '$lib/components/review/rules_guide';
	import RulesGuide from '$lib/components/review/RulesGuide.svelte';
	import { rulesYaml } from '$lib/components/review/rules_export';
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
	let guideOpen = $state(false);
	let simulations = $state<Record<string, RuleSimulation>>({});
	let reload = $state(0);
	let isAdmin = $derived(hasRole(session.user?.roles ?? [], 'admin'));
	let shown = $derived(rules.filter((r) => showInactive || r.active));

	const describe = (e: unknown) =>
		e instanceof ApiError ? (e.status === 501 ? 'The review backend is not connected yet.' : e.detail) : String(e);

	$effect(() => {
		void reload;
		listRules('rules')
			.then((list) => {
				rules = list.items;
				error = '';
			})
			.catch((e) => (error = describe(e)));
	});

	let exportable = $derived(rules.some((r) => r.origin === 'operator' && r.active));

	function download() {
		const now = new Date().toISOString();
		const url = URL.createObjectURL(new Blob([rulesYaml(rules, now)], { type: 'application/yaml' }));
		const a = Object.assign(document.createElement('a'), { href: url, download: `dcl-operator-rules-${now.slice(0, 10)}.yaml` });
		a.click();
		URL.revokeObjectURL(url);
	}

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

	const create = (draft: RuleDraft) =>
		act(async () => savedLine(await createRule(draft), RULE_TYPE_HELP[draft.rule_type].effect));
	const deactivate = (rule: RuleView) =>
		act(async () => (await deactivateRule(rule.rule_id), deactivatedLine(RULE_TYPE_HELP[rule.rule_type].effect)));
	async function simulate(rule: RuleView) {
		try {
			simulations[rule.rule_id] = await simulateRule(rule.rule_id);
		} catch (e) {
			error = describe(e);
		}
	}
	const scopeText = (r: RuleView) =>
		[r.scope.scope_root, r.scope.scope_folder_id && (r.scope_folder_path ?? `folder ${r.scope.scope_folder_id}`), r.scope.scope_filename_glob, r.scope.scope_extension]
			.filter(Boolean)
			.join(' · ') || 'everywhere';
</script>

<RoleGate roles={session.user?.roles ?? []} role="reviewer">
	<Page
		title="Rules"
		description="A rule gives an answer once. The unit of each test-data column in a folder is proposed: every waiting file shows it, and a person checks and applies it file by file. Every other kind acts when saved: it answers the open flags it matches or changes the files it matches. The closest rule wins."
		width="full"
	>
		{#snippet actions()}
			<RulesGuide bind:open={guideOpen} />
			<label class="text-muted-foreground flex items-center gap-2 text-[13px]"><input type="checkbox" bind:checked={showInactive} /> show inactive</label>
			<Button variant="outline" size="sm" disabled={!exportable} onclick={download}>Export YAML</Button>
			<Button variant="outline" size="sm" href="/review"><ArrowLeftIcon />Queue</Button>
		{/snippet}
		<div class="grid gap-6">
			{#if error}<Notice tone="error">{error}</Notice>{/if}
			{#if notice}<Notice tone="success">{notice}</Notice>{/if}
			<RuleWizard onSaved={() => (reload += 1)} />

			<section class="grid gap-3" aria-labelledby="saved-rules-title">
				<h2 id="saved-rules-title" class="m-0 text-base font-semibold">Saved rules</h2>
			{#if shown.length === 0 && !error}
				<EmptyState
					title="No rules yet."
					description="Create one above: choose a folder, say what its columns are, and save. It shows up here the moment it exists."
				/>
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
									<td class="text-muted-foreground text-xs">
										<span class="num">{usageLine(rule, RULE_TYPE_HELP[rule.rule_type].effect)}</span>
										{#if RULE_TYPE_HELP[rule.rule_type].effect === 'proposes' && rule.files_waiting}<br /><a href="/review?proposed_by_rule_id={rule.rule_id}">Review the waiting files</a>{/if}
									</td>
									<td class="text-muted-foreground text-xs">
										{rule.created_by}, <span class="font-mono">{rule.created_at.slice(0, 10)}</span>
										{#if rule.supersedes_rule_id}<br />supersedes <span class="font-mono">{rule.supersedes_rule_id.slice(0, 8)}</span>{/if}
									</td>
									<td>
										<div class="flex justify-end gap-1.5">
											<Button variant="outline" size="xs" onclick={() => simulate(rule)}>Simulate</Button>
											{#if rule.active}<Button variant="outline" size="xs" disabled={busy} title={deactivateTitle(RULE_TYPE_HELP[rule.rule_type].effect)} onclick={() => deactivate(rule)}>{deactivateLabel(RULE_TYPE_HELP[rule.rule_type].effect)}</Button>{/if}
										</div>
									</td>
								</tr>
								{#if simulations[rule.rule_id]}
									{@const sim = simulations[rule.rule_id]}
									<tr class="hover:bg-transparent">
										<td colspan="6" class="bg-muted/40">
											<p class="m-0 text-[13px] font-medium">{simulationLine(sim, RULE_TYPE_HELP[rule.rule_type].effect)}</p>
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
			</section>

			<details class="panel">
				<summary class="panel-header cursor-pointer"><span class="panel-title">Advanced: write a rule as JSON</span></summary>
				<div class="panel-body grid max-w-xl gap-4">
					<p class="text-muted-foreground m-0 text-xs">
						For rule kinds the steps above do not cover. A unit proposal waits for a person; every other kind acts when saved: it answers the open flags it matches or changes the files it matches, and those files are rebuilt. Use Preview to see how many flags it would answer.
					</p>
					<RuleForm {busy} onSubmit={create} />
				</div>
			</details>
		</div>
	</Page>
</RoleGate>

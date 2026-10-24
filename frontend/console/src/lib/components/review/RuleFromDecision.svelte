<script lang="ts">
	// "Make a rule from this decision": shown under the flags after a decision is applied, one card per rule that
	// would repeat it (rule_from_decision.ts). Test-data units are not offered here; they have "Also propose to".
	import type { CaseLocation } from '$lib/api_endpoint';
	import { Button } from '$lib/components/ui/button';
	import Notice from '$lib/components/shell/Notice.svelte';
	import RuleOfferCard from './RuleOfferCard.svelte';
	import type { RuleOffer } from './rule_from_decision';

	interface Props {
		offers: RuleOffer[];
		where: CaseLocation | null;
		onSaved?: () => void;
		onDismiss: () => void;
	}

	let { offers, where, onSaved, onDismiss }: Props = $props();
</script>

<section class="panel" aria-labelledby="rule-from-decision-title">
	<div class="panel-header">
		<div class="grid gap-0.5">
			<h2 id="rule-from-decision-title" class="panel-title">Make a rule from this decision</h2>
			<p class="text-muted-foreground m-0 text-xs">Give the same answer to the same kind of flag in other files of this folder. Saving answers the open flags it matches and rebuilds those files; the file you just decided stays as it is.</p>
		</div>
		<Button variant="ghost" size="sm" onclick={onDismiss}>No thanks</Button>
	</div>
	<div class="panel-body grid gap-3">
		{#if where?.folder_id}
			{#each offers as offer (offer.flagId)}<RuleOfferCard {offer} {where} {onSaved} />{/each}
		{:else}
			<Notice tone="info">This file has no folder to scope a rule to.</Notice>
		{/if}
	</div>
</section>

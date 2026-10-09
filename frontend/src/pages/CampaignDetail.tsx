import { Navigate, useParams } from 'react-router-dom';
import { CampaignDialog, type AccountOption } from '@/components/CampaignDialog';
import { apiGet } from '@/lib/api';
import { useAsync } from '@/lib/hooks';

export function CampaignEditDialog({
  campaignId,
  onClose,
  onSaved,
}: {
  campaignId: number;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const accounts = useAsync<AccountOption[]>(() => apiGet('/api/accounts'), []);
  return (
    <CampaignDialog
      open
      editId={campaignId}
      accounts={accounts.data ?? []}
      onClose={onClose}
      onSaved={onSaved}
    />
  );
}

/* Deep links keep working: /campaign/:id opens the popup over the list. */
export default function CampaignDetail() {
  const { id } = useParams();
  return <Navigate to={`/campaigns?edit=${id}`} replace />;
}

import { Card, SectionHeader, Input, Button } from '@/components/ui'
import { useAuth } from '@/contexts/AuthContext'

export function SettingsPage() {
  const { user } = useAuth()

  return (
    <div className="p-6 max-w-2xl space-y-6">
      <SectionHeader title="Settings" description="Manage your account preferences" />

      <Card>
        <h3 className="text-base font-semibold text-text-primary mb-4">Profile</h3>
        <div className="space-y-4">
          <Input label="Username" value={user?.username || ''} readOnly />
          <Input label="Email" value={user?.email || ''} readOnly />
          <Input label="Role" value={user?.role || ''} readOnly />
        </div>
      </Card>

      <Card>
        <h3 className="text-base font-semibold text-text-primary mb-4">Preferences</h3>
        <p className="text-sm text-text-muted mb-4">
          More settings will be available in future updates.
        </p>
        <Button variant="secondary" disabled>Save Changes</Button>
      </Card>
    </div>
  )
}

# Preview all emails at http://localhost:3000/rails/mailers/account_invitations_mailer
class AccountMailerPreview < ActionMailer::Preview
  # Preview this email at http://localhost:3000/rails/mailers/account_mailer/invite
  def invite
    account = Account.new(name: "Example Account")
    account_invitation = AccountInvitation.new(id: 1, token: "fake", account: account, name: "Test User", email: "test@example.com", invited_by: User.first)
    AccountMailer.with(account_invitation: account_invitation).invite
  end

  def cancellation_reason
    subscription = Pay::Subscription.new(
      type: Pay::FakeProcessor::Subscription,
      customer: Pay::Customer.new(owner: Account.first),
      name: "default",
      processor_id: "fake_1",
      processor_plan: "fake",
      quantity: 1,
      status: "canceled",
      trial_ends_at: 1.week.ago,
      ends_at: Time.current
    )

    # Preview this email at http://localhost:3000/rails/mailers/account_mailer/cancellation_reason
    AccountMailer.with(subscription: subscription).cancellation_reason
  end
end

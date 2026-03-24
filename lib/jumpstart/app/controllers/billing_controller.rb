class BillingController < ApplicationController
  before_action :authenticate_user!
  before_action :require_current_account_admin, except: [:show]

  layout "sidebar"

  def show
    @payment_processor = current_account.payment_processor
    @subscriptions = current_account.pay_subscriptions.active.or(current_account.pay_subscriptions.past_due).or(current_account.pay_subscriptions.unpaid).order(created_at: :asc).includes([:customer])
  end

  def update
    current_account.update(billing_params)
    redirect_to billing_path, notice: t(".updated")
  end

  private

  def billing_params
    params.expect(account: [:extra_billing_info, :billing_email])
  end
end

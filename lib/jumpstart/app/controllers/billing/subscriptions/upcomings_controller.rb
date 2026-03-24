class Billing::Subscriptions::UpcomingsController < ApplicationController
  before_action :authenticate_user!
  before_action :require_current_account_admin
  before_action :set_subscription

  layout "sidebar"

  def show
    @invoice = @subscription.preview_invoice
  rescue Stripe::InvalidRequestError => e
    redirect_to billing_path, alert: e.message
  end

  private

  def set_subscription
    @subscription = current_account.pay_subscriptions.find_by_prefix_id!(params[:subscription_id])
  rescue ActiveRecord::RecordNotFound
    redirect_to billing_path
  end
end

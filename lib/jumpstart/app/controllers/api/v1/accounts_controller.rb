class Api::V1::AccountsController < Api::BaseController
  def index
    @accounts = current_user.accounts
    render "accounts/index"
  end

  def show
    @account = current_user.accounts.find(params[:id])
    render "accounts/show"
  rescue ActiveRecord::RecordNotFound
    render json: {error: "Account not found"}, status: :not_found
  end
end

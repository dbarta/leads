class Api::V1::AccountsController < Api::BaseController
  def index
    @accounts = current_user.accounts
    render "accounts/index"
  end

  def show
    @account = current_user.accounts.find(params[:id])
    render "accounts/show"
  end
end

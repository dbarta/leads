require "test_helper"

class AccountsControllerTest < ActionDispatch::IntegrationTest
  test "returns current user accounts" do
    user = users(:one)
    get api_v1_accounts_url, headers: {Authorization: "token #{user.api_tokens.first.token}"}
    assert_response :success
    assert_includes response.parsed_body.pluck("name"), user.accounts.first.name
  end

  test "returns current user account" do
    user = users(:one)
    account = accounts(:company)
    get api_v1_account_url(account), headers: {Authorization: "token #{user.api_tokens.first.token}"}
    assert_response :success
    assert_includes response.parsed_body["name"], account.name
  end
end

require "test_helper"

class CompaniesControllerTest < ActionDispatch::IntegrationTest
  setup do
    sign_in users(:one)
  end

  test "index responds with success" do
    get companies_url
    assert_response :success
  end

  test "index shows companies" do
    get companies_url
    assert_match "Acme Ground Services", response.body
  end

  test "index filters by qualification status" do
    get companies_url, params: {qualification_status: "Yes"}
    assert_match "Acme Ground Services", response.body
    assert_no_match "Big Airline", response.body
  end

  test "index filters by airport" do
    get companies_url, params: {airport_id: airports(:lax).id}
    assert_match "Acme Ground Services", response.body
  end

  test "index hides airlines" do
    get companies_url, params: {hide_airlines: "1"}
    assert_no_match "Big Airline", response.body
    assert_match "Acme Ground Services", response.body
  end

  test "index searches by name" do
    get companies_url, params: {q: "Acme"}
    assert_match "Acme Ground Services", response.body
    assert_no_match "Big Airline", response.body
  end

  test "show responds with success" do
    get company_url(companies(:acme_ground))
    assert_response :success
    assert_match "Acme Ground Services", response.body
  end
end

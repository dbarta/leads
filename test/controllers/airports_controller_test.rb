require "test_helper"

class AirportsControllerTest < ActionDispatch::IntegrationTest
  setup do
    sign_in users(:one)
  end

  test "index responds with success" do
    get airports_url
    assert_response :success
  end

  test "index shows airport count" do
    get airports_url
    assert_match "Los Angeles", response.body
    assert_match "Chicago", response.body
  end

  test "index filters by state" do
    get airports_url, params: {state: "CA"}
    assert_response :success
    assert_match "Los Angeles", response.body
    assert_no_match "O'Hare", response.body
  end

  test "index searches by faa_code" do
    get airports_url, params: {q: "LAX"}
    assert_response :success
    assert_match "Los Angeles", response.body
    assert_no_match "O'Hare", response.body
  end

  test "index filters by discovery_status" do
    get airports_url, params: {discovery_status: "completed"}
    assert_response :success
    assert_match "O&#39;Hare", response.body
    assert_no_match "Los Angeles Intl", response.body
  end

  test "show responds with success" do
    get airport_url(airports(:lax))
    assert_response :success
    assert_match "Los Angeles", response.body
    assert_match "LAX", response.body
  end

  test "show displays FAA fields" do
    get airport_url(airports(:lax))
    assert_match "KLAX", response.body
    assert_match "Los Angeles World Airports", response.body
  end

  test "redirects unauthenticated users" do
    sign_out :user
    get airports_url
    assert_response :redirect
  end
end

module PlanHelper
  def formatted_plan_interval(plan)
    I18n.t("plan_intervals.#{plan.interval}", count: plan.interval_count)
  end
end

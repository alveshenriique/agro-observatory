-- The method parameters behind the published numbers, from the same dbt variables the models
-- use, for the catalog and the Método page of the site (one row).
select
    {{ var('deflation_base_year') }} as deflation_base_year,
    {{ var('real_value_first_year') }} as real_value_first_year,
    {{ var('coffee_unit_break_year') }} as coffee_unit_break_year,
    2012 as coffee_breakdown_first_year,
    {{ var('climate_first_harvest_year') }} as climate_first_harvest_year,
    {{ var('climate_normal_start_year') }} as climate_normal_start_year,
    {{ var('climate_normal_end_year') }} as climate_normal_end_year,
    {{ var('yield_trend_start_year') }} as yield_trend_start_year,
    {{ var('yield_trend_end_year') }} as yield_trend_end_year,
    {{ var('stress_z_threshold') }} as stress_z_threshold,
    {{ var('heat_tmax_threshold_c') }} as heat_tmax_threshold_c,
    {{ var('heat_min_extra_hot_days') }} as heat_min_extra_hot_days,
    {{ var('frost_tmin_threshold_c') }} as frost_tmin_threshold_c

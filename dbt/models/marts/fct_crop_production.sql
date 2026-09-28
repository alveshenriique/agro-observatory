-- One row per municipality × crop × year with any PAM data. Rows where every variable is
-- "..." or ".." carry no information and are left out; missing combinations mean "no data".

with pam as (
    select * from {{ ref('int_pam__crop_year') }}
    where has_data
),

ipca as (
    select * from {{ ref('int_bcb__ipca_annual') }}
    where is_complete_year
)

select
    pam.municipality_id,
    pam.crop,
    pam.year,

    pam.planted_area_ha,
    pam.planted_area_status,
    pam.harvested_area_ha,
    pam.harvested_area_status,
    pam.production_t,
    pam.production_status,

    -- Recalculated yield; the IBGE figure is kept only for the consistency test.
    case
        when pam.harvested_area_ha > 0 then pam.production_t * 1000 / pam.harvested_area_ha
    end as yield_kg_ha,
    pam.ibge_yield_kg_ha,

    -- Nominal value in the currency of the year (see production_value_unit): not comparable
    -- across currencies, and "Mil Cruzeiros" means two different currencies (1974-1985 and
    -- 1990-1992).
    pam.production_value_nominal_thousand,
    pam.production_value_unit,
    pam.production_value_status,
    -- Real value in thousand BRL at deflation_base_year prices, only from
    -- real_value_first_year on.
    case
        when pam.year >= {{ var('real_value_first_year') }}
            then pam.production_value_nominal_thousand * ipca.deflator_to_base_year
    end as production_value_real_thousand_brl

from pam
left join ipca
    on pam.year = ipca.year

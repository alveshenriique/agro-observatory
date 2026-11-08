-- Scope of the external validation against IBGE's aggregates. The grid downloaded from SIDRA
-- (table 5457, Brazil and the 27 states x 5 crops x 4 variables x every year) splits into the
-- cells IBGE publishes a value for, which are compared (serve_validation_sidra), and the
-- combinations without a published value ("..."), by reason. One row per category; the
-- reasons are checked in this order.
with cells as (
    select
        case
            when official_value is not null then 'compared'
            when crop in ('coffee_arabica', 'coffee_canephora') and year < 2012
                then 'coffee_breakdown_before_2012'
            when variable = 'planted_area_ha' and year < {{ var('planted_area_first_year') }}
                then 'planted_area_before_1988'
            else 'state_year_without_value'
        end as category
    from {{ ref('sidra_official_aggregates') }}
)

select
    category,
    case category
        when 'compared' then 1
        when 'coffee_breakdown_before_2012' then 2
        when 'planted_area_before_1988' then 3
        else 4
    end as sort_order,
    case category
        when 'compared' then 'valor publicado pelo IBGE, comparado com a soma dos municípios'
        when 'coffee_breakdown_before_2012'
            then 'arábica e canéfora antes de 2012, quando a PAM ainda não separava o café'
        when 'planted_area_before_1988'
            then 'área plantada antes de 1988, quando a PAM ainda não a publicava'
        else 'UF em ano sem valor publicado (antes da criação do estado ou sem levantamento)'
    end as description_pt,
    count(*) as cells
from cells
group by category

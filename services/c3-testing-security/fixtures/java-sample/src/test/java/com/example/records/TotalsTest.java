package com.example.records;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.util.List;
import org.junit.jupiter.api.Disabled;
import org.junit.jupiter.api.Test;

/**
 * Enough of a suite to measure, and deliberately not all of one.
 *
 * <p>{@code freeDelivery} has no test at all, and one case here is disabled, so
 * a report over this sample has a coverage number below a hundred, a mutant
 * nothing kills, and a case the framework declined to run. A fixture where
 * everything passed would only prove the harness can report success.
 */
class TotalsTest {

    @Test
    void adds_price_times_quantity_across_the_lines() {
        long total = Totals.total(List.of(new Totals.Line(250, 3), new Totals.Line(100, 1)));

        assertEquals(850, total);
    }

    @Test
    void an_empty_order_is_worth_nothing() {
        assertEquals(0, Totals.total(List.of()));
    }

    @Test
    void a_discount_rounds_to_the_nearest_penny() {
        // 1000 pence less 33 per cent is 670 pence: 67000 tenths, rounded half up.
        assertEquals(670, Totals.discounted(1000, 33));
    }

    @Test
    void a_percentage_outside_the_range_is_refused() {
        assertThrows(IllegalArgumentException.class, () -> Totals.discounted(1000, 101));
    }

    @Test
    @Disabled("the fixture needs one case the framework declined to run")
    void a_discount_in_another_currency() {
        assertEquals(0, Totals.discounted(0, 0));
    }
}

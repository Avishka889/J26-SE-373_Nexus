package com.example.records;

import java.util.List;

/**
 * The part of the sample that exists to be measured rather than to be found.
 *
 * <p>Arithmetic with branches in it, so coverage is a number rather than 100
 * and a mutation pass has something to kill. Nothing in here is a weakness.
 */
public final class Totals {

    private Totals() {}

    /** A line of an order: what it costs and how many. */
    public record Line(long pence, int quantity) {}

    /** The order total in pence. */
    public static long total(List<Line> lines) {
        long sum = 0;
        for (Line line : lines) {
            sum += line.pence() * line.quantity();
        }
        return sum;
    }

    /**
     * The total after a percentage discount, rounded to the nearest penny.
     *
     * <p>Half up rather than half even, because money is counted the way a
     * customer expects rather than the way a float library prefers.
     */
    public static long discounted(long pence, int percent) {
        if (percent < 0 || percent > 100) {
            throw new IllegalArgumentException("a percentage is between 0 and 100");
        }
        long kept = pence * (100L - percent);
        return (kept + 50) / 100;
    }

    /**
     * Whether an order qualifies for free delivery.
     *
     * <p>No test reaches this, on purpose: the fixture has to be able to show
     * a coverage number that is not 100 and a mutant nothing kills.
     */
    public static boolean freeDelivery(long pence, boolean member) {
        if (member) {
            return pence >= 1000;
        }
        return pence >= 5000;
    }
}

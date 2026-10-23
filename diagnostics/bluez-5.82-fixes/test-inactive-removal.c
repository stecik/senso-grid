/* Regression: inactive service removal must invalidate discovery references. */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include "lib/bluetooth.h"
#include "lib/uuid.h"
#include "src/shared/gatt-db.h"

static void removed(struct gatt_db_attribute *attr, void *user_data)
{
    unsigned int *count = user_data;
    (void)attr;
    ++*count;
}

int main(void)
{
    unsigned int count = 0;
    struct gatt_db *db = gatt_db_new();
    bt_uuid_t uuid;
    bt_uuid16_create(&uuid, 0xffe5);
    if (!db || !gatt_db_register(db, NULL, removed, &count, NULL))
        return 2;
    struct gatt_db_attribute *attr = gatt_db_add_service(db, &uuid, true, 4);
    if (!attr || gatt_db_service_get_active(attr) || !gatt_db_remove_service(db, attr))
        return 2;
    printf("inactive service removal notifications: %u (expected 1)\n", count);
    gatt_db_unref(db);
    return count == 1 ? 0 : 1;
}

package com.ghost.tesla.mobile;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

public class BootReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        NotificationCenter.ensureChannels(context);
        NotificationCenter.schedule(context);
    }
}

import {
  to = aws_instance.api
  id = "i-0cf3e4052471fccaf"
}
import {
  to = aws_ebs_volume.data
  id = "vol-0582f8e96ea04955b"
}
import {
  to = aws_volume_attachment.data
  id = "/dev/sdf:vol-0582f8e96ea04955b:i-0cf3e4052471fccaf"
}
import {
  to = aws_eip.api
  id = "eipalloc-04761da854170e997"
}
import {
  to = aws_security_group.api
  id = "sg-0c1f3e4b97e20f9c7"
}
